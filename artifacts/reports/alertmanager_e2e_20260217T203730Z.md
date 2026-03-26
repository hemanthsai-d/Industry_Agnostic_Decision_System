# Alertmanager E2E Drill Evidence

- Timestamp (UTC): 20260217T203730Z
- Mode: local
- Alertmanager URL: http://127.0.0.1:9093
- Active config: observability/alertmanager/alertmanager.yml
- Posted alerts payload: /tmp/decision_alertmanager_e2e_payload_20260217T203730Z.json
- Validation: local mode: webhook sink confirmed pager/model/platform/ticket deliveries
- Webhook events file: /Users/hemanthsai/Desktop/decision-platform-baseline/artifacts/reports/alert_webhook_events_20260217T203730Z.jsonl
- Webhook summary file: /Users/hemanthsai/Desktop/decision-platform-baseline/artifacts/reports/alert_webhook_summary_20260217T203730Z.json

## Webhook Summary

```json
{"total":5,"counts":{"/platform-oncall":2,"/model-oncall":1,"/pager":1,"/ticket":1},"events_path":"/Users/hemanthsai/Desktop/decision-platform-baseline/artifacts/reports/alert_webhook_events_20260217T203730Z.jsonl"}
```
