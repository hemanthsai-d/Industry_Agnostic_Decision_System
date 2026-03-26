# Business KPI Scorecard

- Generated at (UTC): 2026-02-18T00:23:35.677308+00:00
- Current window: 2026-01-22 -> 2026-02-18
- Baseline window: 2025-12-25 -> 2026-01-21
- Tenant filter: __all__
- Section filter: __all__
- Model variant: primary

| KPI | Target | Actual | Status |
|---|---:|---:|---|
| `agent_weekly_active_usage_pct` | >= 70.00% | 0.00% | `fail` |
| `assisted_coverage_pct` | >= 80.00% | 186.60% | `pass` |
| `ece` | <= 10.00% | n/a | `insufficient_data` |
| `escalation_precision_pct` | >= 80.00% | n/a | `insufficient_data` |
| `escalation_rate_reduction_pct` | >= 20.00% | n/a | `insufficient_data` |
| `escalation_recall_pct` | >= 75.00% | n/a | `insufficient_data` |
| `feedback_completeness_pct` | >= 95.00% | n/a | `insufficient_data` |
| `median_handling_time_reduction_pct` | >= 25.00% | n/a | `insufficient_data` |
| `p90_handling_time_reduction_pct` | >= 15.00% | n/a | `insufficient_data` |
| `top1_route_accuracy_pct` | >= 85.00% | n/a | `insufficient_data` |

## KPI Details

### `agent_weekly_active_usage_pct`
- Description: Weekly active usage = active reviewers / active agents
- Details: `{"active_agents_7d":43,"active_reviewers_7d":0}`

### `assisted_coverage_pct`
- Description: Assisted coverage = assisted eligible tickets / eligible tickets
- Details: `{"eligible_tickets":3358,"assisted_requests":6266}`

### `ece`
- Description: Expected Calibration Error
- Details: `{"ece_bins":0}`

### `escalation_precision_pct`
- Description: Escalation precision for labeled decisions
- Details: `{"predicted_escalations":null,"true_positive_escalations":null}`

### `escalation_rate_reduction_pct`
- Description: Escalation rate reduction vs baseline window
- Details: `{"current_escalation_rate":null,"baseline_escalation_rate":null}`

### `escalation_recall_pct`
- Description: Escalation recall for labeled decisions
- Details: `{"actual_escalations":null,"true_positive_escalations":null}`

### `feedback_completeness_pct`
- Description: Closed handoffs with reviewer outcomes
- Details: `{"closed_handoffs":0,"closed_with_outcome":0}`

### `median_handling_time_reduction_pct`
- Description: Median handling time reduction vs baseline
- Details: `{"current_p50_seconds":null,"baseline_p50_seconds":null}`

### `p90_handling_time_reduction_pct`
- Description: P90 handling time reduction vs baseline
- Details: `{"current_p90_seconds":null,"baseline_p90_seconds":null}`

### `top1_route_accuracy_pct`
- Description: Top-1 route accuracy for labeled decisions
- Details: `{"labeled_samples":0}`
