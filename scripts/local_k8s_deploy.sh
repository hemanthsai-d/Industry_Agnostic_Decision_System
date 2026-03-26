#!/usr/bin/env bash
# scripts/local_k8s_deploy.sh
#
# One-command local Kubernetes deployment using kind.
# Creates a kind cluster, builds and loads Docker images, and deploys
# the decision-platform via Helm with local overrides.
#
# Prerequisites: docker, kind, kubectl, helm
#
# Usage:
#   ./scripts/local_k8s_deploy.sh          # full deploy
#   ./scripts/local_k8s_deploy.sh teardown  # destroy cluster
#   ./scripts/local_k8s_deploy.sh redeploy  # rebuild images + helm upgrade
#   ./scripts/local_k8s_deploy.sh status    # show pod/svc status

set -euo pipefail

CLUSTER_NAME="decision-platform"
NAMESPACE="local"
KIND_CONFIG="infra/kind-cluster.yaml"
HELM_CHART="infra/helm/decision-platform"
HELM_VALUES="infra/helm/values-local.yaml"
API_IMAGE="decision-api:local"
MODEL_IMAGE="model-server:local"

# ── Colours ──────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

info()  { echo -e "${CYAN}[INFO]${NC}  $*"; }
ok()    { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
err()   { echo -e "${RED}[ERR]${NC}   $*" >&2; }

# ── Prerequisite checks ─────────────────────────
check_prereqs() {
    local missing=0
    for cmd in docker kind kubectl helm; do
        if ! command -v "$cmd" &>/dev/null; then
            err "Required command not found: $cmd"
            missing=1
        fi
    done
    if [[ $missing -ne 0 ]]; then
        echo ""
        echo "Install missing tools:"
        echo "  brew install kind kubectl helm    # macOS"
        echo "  Docker Desktop: https://www.docker.com/products/docker-desktop"
        exit 1
    fi

    if ! docker info &>/dev/null; then
        err "Docker daemon is not running. Start Docker Desktop first."
        exit 1
    fi
}

# ── Cluster management ──────────────────────────
cluster_exists() {
    kind get clusters 2>/dev/null | grep -q "^${CLUSTER_NAME}$"
}

create_cluster() {
    if cluster_exists; then
        info "Kind cluster '${CLUSTER_NAME}' already exists — skipping creation."
    else
        info "Creating kind cluster '${CLUSTER_NAME}'..."
        kind create cluster --config "${KIND_CONFIG}" --name "${CLUSTER_NAME}" --wait 60s
        ok "Cluster created."
    fi
    kubectl cluster-info --context "kind-${CLUSTER_NAME}"
}

teardown_cluster() {
    if cluster_exists; then
        info "Deleting kind cluster '${CLUSTER_NAME}'..."
        kind delete cluster --name "${CLUSTER_NAME}"
        ok "Cluster deleted."
    else
        warn "Cluster '${CLUSTER_NAME}' does not exist."
    fi
}

# ── Image build & load ──────────────────────────
build_images() {
    info "Building decision-api image..."
    docker build -t "${API_IMAGE}" -f Dockerfile .
    ok "decision-api image built."

    info "Building model-server image..."
    docker build -t "${MODEL_IMAGE}" -f model_server/Dockerfile .
    ok "model-server image built."
}

load_images() {
    info "Loading images into kind cluster..."
    kind load docker-image "${API_IMAGE}" --name "${CLUSTER_NAME}"
    kind load docker-image "${MODEL_IMAGE}" --name "${CLUSTER_NAME}"
    ok "Images loaded into cluster."
}

# ── Helm deploy ─────────────────────────────────
helm_deploy() {
    info "Updating Helm dependencies..."
    helm dependency update "${HELM_CHART}" 2>/dev/null || warn "Helm dependency update had warnings (non-fatal)."

    info "Deploying decision-platform to namespace '${NAMESPACE}'..."
    helm upgrade --install decision-api "${HELM_CHART}" \
        --namespace "${NAMESPACE}" --create-namespace \
        --values "${HELM_VALUES}" \
        --set image.repository=decision-api \
        --set image.tag=local \
        --set modelServer.image.repository=model-server \
        --set modelServer.image.tag=local \
        --wait --timeout 300s

    ok "Helm release deployed."
}

# ── Status ──────────────────────────────────────
show_status() {
    echo ""
    info "=== Pods ==="
    kubectl get pods -n "${NAMESPACE}" -o wide 2>/dev/null || warn "No pods found."
    echo ""
    info "=== Services ==="
    kubectl get svc -n "${NAMESPACE}" 2>/dev/null || warn "No services found."
    echo ""
    info "=== Endpoints ==="
    echo "  Decision API:   http://localhost:30080/health"
    echo "  Decision API:   http://localhost:30080/ready"
    echo "  Decision API:   http://localhost:30080/api/v1/decide"
    echo ""
}

wait_for_pods() {
    info "Waiting for pods to be ready (up to 120s)..."
    kubectl wait --for=condition=ready pod \
        --all -n "${NAMESPACE}" \
        --timeout=120s 2>/dev/null || warn "Some pods may not be ready yet."
}

# ── Main ────────────────────────────────────────
main() {
    local action="${1:-deploy}"

    case "$action" in
        deploy)
            check_prereqs
            create_cluster
            build_images
            load_images
            helm_deploy
            wait_for_pods
            show_status
            ok "Local Kubernetes deployment complete!"
            echo ""
            echo "Quick test:"
            echo "  curl http://localhost:30080/health"
            echo ""
            echo "Teardown:"
            echo "  ./scripts/local_k8s_deploy.sh teardown"
            ;;
        teardown|destroy|delete)
            check_prereqs
            teardown_cluster
            ;;
        redeploy|upgrade)
            check_prereqs
            build_images
            load_images
            helm_deploy
            wait_for_pods
            show_status
            ok "Redeploy complete!"
            ;;
        status)
            show_status
            ;;
        images)
            check_prereqs
            build_images
            load_images
            ok "Images rebuilt and loaded."
            ;;
        *)
            echo "Usage: $0 {deploy|teardown|redeploy|status|images}"
            exit 1
            ;;
    esac
}

main "$@"
