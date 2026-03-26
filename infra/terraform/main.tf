# Terraform — GKE / EKS infrastructure for Decision Platform
#
# This provisions the core cloud infrastructure:
#   - Kubernetes cluster (GKE or EKS)
#   - Cloud SQL / RDS (PostgreSQL with pgvector)
#   - Memorystore / ElastiCache (Redis)
#   - VPC, subnets, NAT, firewall rules
#   - IAM service accounts
#   - Secret Manager / KMS
#
# Usage:
#   cd infra/terraform
#   terraform init
#   terraform plan -var-file=environments/production.tfvars
#   terraform apply -var-file=environments/production.tfvars

terraform {
  required_version = ">= 1.5"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
  }

  backend "gcs" {
    bucket = "decision-platform-tfstate"
    prefix = "terraform/state"
  }
}

# ──────────────────────────────────────────────────
# Variables
# ──────────────────────────────────────────────────

variable "project_id" {
  type        = string
  description = "GCP project ID"
}

variable "region" {
  type    = string
  default = "us-central1"
}

variable "environment" {
  type    = string
  default = "production"
}

variable "cluster_name" {
  type    = string
  default = "decision-platform"
}

variable "db_tier" {
  type    = string
  default = "db-custom-4-16384"  # 4 vCPU, 16 GB RAM
}

variable "redis_memory_size_gb" {
  type    = number
  default = 2
}

variable "min_node_count" {
  type    = number
  default = 3
}

variable "max_node_count" {
  type    = number
  default = 20
}

# ──────────────────────────────────────────────────
# VPC
# ──────────────────────────────────────────────────

resource "google_compute_network" "vpc" {
  name                    = "${var.cluster_name}-vpc"
  auto_create_subnetworks = false
  project                 = var.project_id
}

resource "google_compute_subnetwork" "nodes" {
  name          = "${var.cluster_name}-nodes"
  ip_cidr_range = "10.0.0.0/20"
  region        = var.region
  network       = google_compute_network.vpc.id
  project       = var.project_id

  secondary_ip_range {
    range_name    = "pods"
    ip_cidr_range = "10.4.0.0/14"
  }
  secondary_ip_range {
    range_name    = "services"
    ip_cidr_range = "10.8.0.0/20"
  }

  private_ip_google_access = true
}

resource "google_compute_router" "router" {
  name    = "${var.cluster_name}-router"
  region  = var.region
  network = google_compute_network.vpc.id
  project = var.project_id
}

resource "google_compute_router_nat" "nat" {
  name                               = "${var.cluster_name}-nat"
  router                             = google_compute_router.router.name
  region                             = var.region
  nat_ip_allocate_option             = "AUTO_ONLY"
  source_subnetwork_ip_ranges_to_nat = "ALL_SUBNETWORKS_ALL_IP_RANGES"
  project                            = var.project_id
}

# ──────────────────────────────────────────────────
# GKE Cluster
# ──────────────────────────────────────────────────

resource "google_container_cluster" "primary" {
  name     = var.cluster_name
  location = var.region
  project  = var.project_id

  # Autopilot or Standard
  enable_autopilot = false

  network    = google_compute_network.vpc.id
  subnetwork = google_compute_subnetwork.nodes.id

  ip_allocation_policy {
    cluster_secondary_range_name  = "pods"
    services_secondary_range_name = "services"
  }

  # Security
  private_cluster_config {
    enable_private_nodes    = true
    enable_private_endpoint = false
    master_ipv4_cidr_block  = "172.16.0.0/28"
  }

  master_auth {
    client_certificate_config {
      issue_client_certificate = false
    }
  }

  # Workload Identity for pod-level IAM
  workload_identity_config {
    workload_pool = "${var.project_id}.svc.id.goog"
  }

  # Network policy enforcement
  network_policy {
    enabled  = true
    provider = "CALICO"
  }

  # Binary Authorization
  binary_authorization {
    evaluation_mode = "PROJECT_SINGLETON_POLICY_ENFORCE"
  }

  # Logging & monitoring
  logging_service    = "logging.googleapis.com/kubernetes"
  monitoring_service = "monitoring.googleapis.com/kubernetes"

  # Initial node pool removed — we use separately managed pools
  remove_default_node_pool = true
  initial_node_count       = 1

  release_channel {
    channel = "REGULAR"
  }
}

resource "google_container_node_pool" "primary_nodes" {
  name     = "${var.cluster_name}-pool"
  location = var.region
  cluster  = google_container_cluster.primary.name
  project  = var.project_id

  autoscaling {
    min_node_count = var.min_node_count
    max_node_count = var.max_node_count
  }

  node_config {
    machine_type = "e2-standard-4"  # 4 vCPU, 16 GB
    disk_size_gb = 100
    disk_type    = "pd-ssd"

    oauth_scopes = [
      "https://www.googleapis.com/auth/cloud-platform",
    ]

    workload_metadata_config {
      mode = "GKE_METADATA"
    }

    shielded_instance_config {
      enable_secure_boot = true
    }
  }

  management {
    auto_repair  = true
    auto_upgrade = true
  }
}

# ──────────────────────────────────────────────────
# Cloud SQL (PostgreSQL + pgvector)
# ──────────────────────────────────────────────────

resource "google_sql_database_instance" "postgres" {
  name             = "${var.cluster_name}-db"
  database_version = "POSTGRES_16"
  region           = var.region
  project          = var.project_id

  settings {
    tier              = var.db_tier
    availability_type = "REGIONAL"  # multi-zone HA

    backup_configuration {
      enabled                        = true
      point_in_time_recovery_enabled = true
      start_time                     = "03:00"
      transaction_log_retention_days = 7

      backup_retention_settings {
        retained_backups = 30
      }
    }

    ip_configuration {
      ipv4_enabled    = false
      private_network = google_compute_network.vpc.id
      require_ssl     = true  # mTLS between app and DB
    }

    database_flags {
      name  = "cloudsql.enable_pgvector"
      value = "on"
    }

    disk_autoresize       = true
    disk_autoresize_limit = 500  # GB
    disk_type             = "PD_SSD"

    insights_config {
      query_insights_enabled  = true
      record_application_tags = true
    }
  }

  deletion_protection = true
}

resource "google_sql_database" "decision_db" {
  name     = "decision_db"
  instance = google_sql_database_instance.postgres.name
  project  = var.project_id
}

# ──────────────────────────────────────────────────
# Memorystore (Redis)
# ──────────────────────────────────────────────────

resource "google_redis_instance" "redis" {
  name               = "${var.cluster_name}-redis"
  tier               = "STANDARD_HA"  # multi-zone HA with automatic failover
  memory_size_gb     = var.redis_memory_size_gb
  region             = var.region
  project            = var.project_id
  authorized_network = google_compute_network.vpc.id
  redis_version      = "REDIS_7_0"
  transit_encryption_mode = "SERVER_AUTHENTICATION"  # TLS in transit

  maintenance_policy {
    weekly_maintenance_window {
      day = "SUNDAY"
      start_time {
        hours   = 4
        minutes = 0
      }
    }
  }
}

# ──────────────────────────────────────────────────
# Secret Manager
# ──────────────────────────────────────────────────

resource "google_secret_manager_secret" "jwt_secret" {
  secret_id = "${var.cluster_name}-jwt-secret"
  project   = var.project_id

  replication {
    auto {}
  }

  rotation {
    rotation_period = "7776000s"  # 90 days
  }
}

resource "google_secret_manager_secret" "db_password" {
  secret_id = "${var.cluster_name}-db-password"
  project   = var.project_id

  replication {
    auto {}
  }

  rotation {
    rotation_period = "7776000s"  # 90 days
  }
}

# ──────────────────────────────────────────────────
# IAM — Workload Identity binding
# ──────────────────────────────────────────────────

resource "google_service_account" "decision_api" {
  account_id   = "${var.cluster_name}-api"
  display_name = "Decision Platform API"
  project      = var.project_id
}

resource "google_project_iam_member" "secret_accessor" {
  project = var.project_id
  role    = "roles/secretmanager.secretAccessor"
  member  = "serviceAccount:${google_service_account.decision_api.email}"
}

resource "google_project_iam_member" "pubsub_publisher" {
  project = var.project_id
  role    = "roles/pubsub.publisher"
  member  = "serviceAccount:${google_service_account.decision_api.email}"
}

resource "google_service_account_iam_member" "workload_identity" {
  service_account_id = google_service_account.decision_api.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "serviceAccount:${var.project_id}.svc.id.goog[production/${var.cluster_name}]"
}

# ──────────────────────────────────────────────────
# Outputs
# ──────────────────────────────────────────────────

output "cluster_endpoint" {
  value     = google_container_cluster.primary.endpoint
  sensitive = true
}

output "db_connection_name" {
  value = google_sql_database_instance.postgres.connection_name
}

output "redis_host" {
  value = google_redis_instance.redis.host
}
