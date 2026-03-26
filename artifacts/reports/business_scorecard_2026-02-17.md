# Business KPI Scorecard

- Generated at (UTC): 2026-02-18T23:16:47.279887+00:00
- Current window: 2026-01-21 -> 2026-02-17
- Baseline window: 2025-12-24 -> 2026-01-20
- Tenant filter: __all__
- Section filter: __all__
- Model variant: primary

| KPI | Target | Actual | Status |
|---|---:|---:|---|
| `agent_weekly_active_usage_pct` | >= 70.00% | 83.72% | `pass` |
| `assisted_coverage_pct` | >= 80.00% | 612.13% | `pass` |
| `ece` | <= 10.00% | 6.56% | `pass` |
| `escalation_precision_pct` | >= 80.00% | 86.54% | `pass` |
| `escalation_rate_reduction_pct` | >= 20.00% | 35.02% | `pass` |
| `escalation_recall_pct` | >= 75.00% | 84.56% | `pass` |
| `feedback_completeness_pct` | >= 95.00% | 100.00% | `pass` |
| `median_handling_time_reduction_pct` | >= 25.00% | 57.37% | `pass` |
| `p90_handling_time_reduction_pct` | >= 15.00% | 56.08% | `pass` |
| `top1_route_accuracy_pct` | >= 85.00% | 86.78% | `pass` |

## KPI Details

### `agent_weekly_active_usage_pct`
- Description: Weekly active usage = active reviewers / active agents
- Details: `{"active_agents_7d":43,"active_reviewers_7d":36}`

### `assisted_coverage_pct`
- Description: Assisted coverage = assisted eligible tickets / eligible tickets
- Details: `{"eligible_tickets":3478,"assisted_requests":21290}`

### `ece`
- Description: Expected Calibration Error
- Details: `{"ece_bins":3}`

### `escalation_precision_pct`
- Description: Escalation precision for labeled decisions
- Details: `{"predicted_escalations":1367,"true_positive_escalations":1183}`

### `escalation_rate_reduction_pct`
- Description: Escalation rate reduction vs baseline window
- Details: `{"current_escalation_rate":0.1894893674657998,"baseline_escalation_rate":0.29161995515695066}`

### `escalation_recall_pct`
- Description: Escalation recall for labeled decisions
- Details: `{"actual_escalations":1399,"true_positive_escalations":1183}`

### `feedback_completeness_pct`
- Description: Closed handoffs with reviewer outcomes
- Details: `{"closed_handoffs":1730,"closed_with_outcome":1730}`

### `median_handling_time_reduction_pct`
- Description: Median handling time reduction vs baseline
- Details: `{"current_p50_seconds":214,"baseline_p50_seconds":502}`

### `p90_handling_time_reduction_pct`
- Description: P90 handling time reduction vs baseline
- Details: `{"current_p90_seconds":361,"baseline_p90_seconds":822}`

### `top1_route_accuracy_pct`
- Description: Top-1 route accuracy for labeled decisions
- Details: `{"labeled_samples":7383}`
