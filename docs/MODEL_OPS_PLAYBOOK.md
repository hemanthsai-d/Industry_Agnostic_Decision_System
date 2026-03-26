# Model Ops Rollback + Retrain Playbook

## Scope

This playbook covers:
1. Ground-truth capture and daily evaluation.
2. Canary promotion gates.
3. Drift/quality-triggered rollback.
4. Probability recalibration + challenger retraining cycle.

## Daily Runbook

1. Build daily joined dataset:
```bash
make evaluate-daily
```
2. Compute daily metrics:
```bash
make evaluate-metrics
```
3. Run drift checks (fails on alerts):
```bash
make drift-check
```
4. Gate canary promotion:
```bash
make promote-canary
```
5. Recalibrate probabilities weekly (or after drift events):
```bash
make recalibrate-models
```
6. Validate live rollout criteria and generate evidence report:
```bash
.venv/bin/python -m scripts.validate_live_rollout \
  --stable-days-min 14 \
  --stable-days-max 28 \
  --min-daily-samples 50 \
  --min-ground-truth 50 \
  --min-calibration-samples 200 \
  --max-calibration-age-days 7 \
  --prometheus-url http://prometheus.monitoring.svc.cluster.local:9090 \
  --fail-on-blocked
```

## Quality Gates for Promotion

Promotion stages are fixed: `0 -> 5 -> 25 -> 50 -> 100`.

Gate evaluation source scope:
1. `canary_percent=0`: challenger shadow+canary predictions (`source LIKE shadow:%`) are used.
2. `canary_percent>0`: challenger canary-only predictions (`source=shadow:canary`) are used.

Promotion proceeds only when challenger metrics over the lookback window meet:
1. `route_accuracy >= quality_gate_min_route_accuracy`
2. `escalation_recall >= quality_gate_min_escalation_recall`
3. `ece <= quality_gate_max_ece`
4. `abstain_rate <= quality_gate_max_abstain_rate`
5. `sample_size >= quality_gate_min_sample_size`

Configured in `model_rollout_config` (`config_id=primary`).

## Rollback Triggers

Rollback should be executed when any condition is met:
1. SLO breach in API/model-serving alerts.
2. Drift alerts sustained (`input`, `confidence`, or `outcome`).
3. Canary quality gate failure after promotion.
4. Guardrail fallback spike (`assist_model_guardrail_fallback_total`).

## Rollback Procedure

1. Evaluate gates and rollback one stage on failure:
```bash
.venv/bin/python -m scripts.promote_canary --lookback-days 14 --apply --rollback-on-fail
```
2. Verify rollout percent changed in `model_rollout_config`.
3. Confirm `/ready` stays healthy and API error rate returns within SLO.
4. Keep rollback stage until retraining/recalibration fixes are validated.

## Retrain + Recalibration Procedure

1. Ensure latest ground truth is present (closed tickets with reviewer outcome fields).
2. Rebuild evaluation dataset/metrics:
```bash
make model-ops-daily
```
3. Refit calibration artifacts:
```bash
make recalibrate-models
```
4. Publish updated artifacts and rerun shadow/challenger checks.
5. Resume gated promotion only after stability window passes.

## Drill (Run at Least Once)

Quarterly drill checklist:
1. Trigger a canary gate evaluation in dry mode:
```bash
.venv/bin/python -m scripts.promote_canary --lookback-days 14 --fail-on-blocked
```
2. Trigger rollback-on-fail path in a non-production environment:
```bash
.venv/bin/python -m scripts.promote_canary --lookback-days 14 --apply --rollback-on-fail
```
3. Run end-to-end daily model-ops pipeline:
```bash
make model-ops-daily
```
4. Record drill timestamp, operator, and outcome in operational notes.

## Evidence to Keep

For each promotion/rollback decision, retain:
1. `evaluation_daily_metrics` snapshot rows.
2. `drift_daily_metrics` rows.
3. Current and previous `model_rollout_config` values.
4. Calibration run entries from `model_calibration_runs`.
5. Promotion/rollback gate events from `model_rollout_events`.
6. Validation reports from `rollout_validation_reports`.
7. Generated report files in `artifacts/reports/live_rollout_validation_<date>.{json,md}`.
