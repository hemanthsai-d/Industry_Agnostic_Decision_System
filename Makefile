.PHONY: setup setup-integrations migrate-db migrate-status seed-db seed-db-reset init-db gen-token run-api run-model-serving run-mcp test test-integration-rate-limit lint lint-fix prod-check evaluate-daily evaluate-metrics drift-check business-scorecard workload-feed oncall-audit verify-incident-endpoints security-audit nonfunctional-load nonfunctional-soak nonfunctional-failure production-readiness-gate production-completion-live model-ops-daily recalibrate-models promote-canary validate-live-rollout build-chatbot-assets import-retrieval-seed configure-alertmanager-prod alertmanager-e2e-drill docker-up docker-up-policy docker-up-model-serving docker-up-observability docker-up-observability-full docker-down bootstrap-gate-data bootstrap-gate-data-reset full-bootstrap download-bitext import-bitext-training bitext-pipeline reindex-embeddings reindex-embeddings-dry-run k8s-local-deploy k8s-local-teardown k8s-local-redeploy k8s-local-status k8s-local-images

setup:
	./scripts/setup.sh

setup-integrations:
	.venv/bin/python -m pip install -r requirements-optional.txt

migrate-db:
	.venv/bin/python -m scripts.migrate migrate

migrate-status:
	.venv/bin/python -m scripts.migrate status

seed-db:
	.venv/bin/python -m scripts.seed_db

seed-db-reset:
	.venv/bin/python -m scripts.seed_db --reset

init-db: migrate-db seed-db
	@echo 'DB ready (migrations + seed).'

gen-token:
	.venv/bin/python -m scripts.generate_token

run-api:
	.venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

run-model-serving:
	.venv/bin/python -m uvicorn model_server.app:app --host 0.0.0.0 --port 9000 --reload

run-mcp:
	.venv/bin/python -m mcp_server.server

test:
	.venv/bin/python -m pytest -q

test-integration-rate-limit:
	bash ./scripts/test_rate_limit_redis_integration.sh

lint:
	.venv/bin/python -m scripts.static_check app model_server mcp_server scripts tests

lint-fix:
	@echo 'No auto-fix step configured for static parser checks.'

prod-check:
	.venv/bin/python -m scripts.preflight_check --env production

evaluate-daily:
	.venv/bin/python -m scripts.build_daily_evaluation

evaluate-metrics:
	.venv/bin/python -m scripts.compute_daily_metrics

drift-check:
	.venv/bin/python -m scripts.compute_drift_metrics --fail-on-alert

business-scorecard:
	.venv/bin/python -m scripts.compute_business_scorecard

workload-feed:
	@if [ -z "$$WORKLOAD_CSV" ]; then \
		echo "Set WORKLOAD_CSV=/path/to/workload.csv"; \
		exit 1; \
	fi
	.venv/bin/python -m scripts.upsert_workload_feed --csv "$$WORKLOAD_CSV" --ensure-tenants --check-gaps-days 28 --fail-on-gaps

oncall-audit:
	@if [ -f "ops/oncall.production.json" ]; then \
		.venv/bin/python -m scripts.audit_oncall_config --config ops/oncall.production.json; \
	else \
		echo "ops/oncall.production.json not found, using ops/oncall.production.example.json"; \
		.venv/bin/python -m scripts.audit_oncall_config --config ops/oncall.production.example.json; \
	fi

verify-incident-endpoints:
	.venv/bin/python -m scripts.verify_incident_endpoints_live --mode live --run-drill

security-audit:
	.venv/bin/python -m scripts.security_compliance_audit --require-production

nonfunctional-load:
	.venv/bin/python -m scripts.run_nonfunctional_validation --mode load --duration-seconds 120 --concurrency 20

nonfunctional-soak:
	.venv/bin/python -m scripts.run_nonfunctional_validation --mode soak --duration-seconds 900 --concurrency 10

nonfunctional-failure:
	.venv/bin/python -m scripts.run_nonfunctional_validation --mode failure --duration-seconds 180 --concurrency 8

production-readiness-gate:
	@if [ -n "$$PROMETHEUS_URL" ]; then \
		.venv/bin/python -m scripts.production_readiness_gate --prometheus-url "$$PROMETHEUS_URL" --fail-on-blocked; \
	else \
		.venv/bin/python -m scripts.production_readiness_gate --skip-slo-check --fail-on-blocked; \
	fi

production-completion-live:
	bash ./scripts/run_production_completion.sh

model-ops-daily:
	.venv/bin/python -m scripts.run_model_ops_daily --fail-on-drift-alert

recalibrate-models:
	.venv/bin/python -m scripts.recalibrate_models --lookback-days 30 --model-variant primary

promote-canary:
	.venv/bin/python -m scripts.promote_canary --lookback-days 14 --apply --fail-on-blocked

validate-live-rollout:
	@if [ -n "$$PROMETHEUS_URL" ]; then \
		.venv/bin/python -m scripts.validate_live_rollout --stable-days-min 14 --stable-days-max 28 --min-daily-samples 50 --min-ground-truth 50 --min-calibration-samples 200 --max-calibration-age-days 7 --prometheus-url "$$PROMETHEUS_URL" --fail-on-blocked; \
	else \
		.venv/bin/python -m scripts.validate_live_rollout --stable-days-min 14 --stable-days-max 28 --min-daily-samples 50 --min-ground-truth 50 --min-calibration-samples 200 --max-calibration-age-days 7 --skip-slo-check --fail-on-blocked; \
	fi

build-chatbot-assets:
	@if [ -z "$$TWITTER_CSV" ] && [ -z "$$ABCD_PATH" ] && [ -z "$$BITEXT_CSV" ]; then \
		echo "Set TWITTER_CSV=/path/to/twcs.csv and/or ABCD_PATH=/path/to/abcd.json and/or BITEXT_CSV=/path/to/bitext.csv"; \
		exit 1; \
	fi
	.venv/bin/python -m scripts.build_external_chatbot_assets \
		$${TWITTER_CSV:+--twitter-csv "$$TWITTER_CSV"} \
		$${ABCD_PATH:+--abcd-path "$$ABCD_PATH"} \
		$${BITEXT_CSV:+--bitext-csv "$$BITEXT_CSV"} \
		$${INTENT_OUTPUT:+--intent-output "$$INTENT_OUTPUT"}

import-retrieval-seed:
	@if [ -z "$$POSTGRES_DSN" ]; then \
		echo "Set POSTGRES_DSN=postgresql://..."; \
		exit 1; \
	fi
	@if [ -z "$$RETRIEVAL_SEED_JSONL" ]; then \
		echo "Set RETRIEVAL_SEED_JSONL=artifacts/datasets/retrieval_seed_chunks.jsonl"; \
		exit 1; \
	fi
	.venv/bin/python -m scripts.import_retrieval_seed_chunks --dsn "$$POSTGRES_DSN" --jsonl "$$RETRIEVAL_SEED_JSONL" --ensure-tenants

configure-alertmanager-prod:
	.venv/bin/python -m scripts.configure_alertmanager_prod --activate

alertmanager-e2e-drill:
	./scripts/run_alertmanager_e2e.sh

docker-up:
	docker compose up -d postgres redis

docker-up-policy:
	docker compose --profile policy up -d opa

docker-up-model-serving:
	docker compose --profile model-serving up -d model-serving

docker-up-observability:
	docker compose --profile observability up -d prometheus grafana alertmanager jaeger

docker-up-observability-full:
	docker compose --profile observability --profile model-serving up -d model-serving prometheus grafana alertmanager jaeger

docker-down:
	docker compose down

bootstrap-gate-data:
	.venv/bin/python -m scripts.bootstrap_production_data

bootstrap-gate-data-reset:
	.venv/bin/python -m scripts.bootstrap_production_data --reset

full-bootstrap: init-db bootstrap-gate-data prod-check
	@echo 'Full bootstrap complete (migrations + seed + gate data + preflight).'

download-bitext:
	.venv/bin/python -m scripts.download_bitext_dataset

import-bitext-training:
	.venv/bin/python -m scripts.import_bitext_training_data

import-bitext-training-reset:
	.venv/bin/python -m scripts.import_bitext_training_data --reset

bitext-pipeline: download-bitext
	BITEXT_CSV=artifacts/datasets/bitext_customer_support.csv .venv/bin/python -m scripts.build_external_chatbot_assets --bitext-csv artifacts/datasets/bitext_customer_support.csv
	POSTGRES_DSN=postgresql://postgres:postgres@localhost:65432/decision_db RETRIEVAL_SEED_JSONL=artifacts/datasets/retrieval_seed_chunks.jsonl .venv/bin/python -m scripts.import_retrieval_seed_chunks --dsn "postgresql://postgres:postgres@localhost:65432/decision_db" --jsonl artifacts/datasets/retrieval_seed_chunks.jsonl --ensure-tenants
	.venv/bin/python -m scripts.import_bitext_training_data --reset
	@echo 'Bitext pipeline complete (download + assets + retrieval chunks + training data).'

reindex-embeddings:
	.venv/bin/python -m scripts.reindex_embeddings

reindex-embeddings-dry-run:
	.venv/bin/python -m scripts.reindex_embeddings --dry-run

# ── Local Kubernetes (kind) ──────────────────────
k8s-local-deploy:
	bash ./scripts/local_k8s_deploy.sh deploy

k8s-local-teardown:
	bash ./scripts/local_k8s_deploy.sh teardown

k8s-local-redeploy:
	bash ./scripts/local_k8s_deploy.sh redeploy

k8s-local-status:
	bash ./scripts/local_k8s_deploy.sh status

k8s-local-images:
	bash ./scripts/local_k8s_deploy.sh images
