#!/usr/bin/env python3
"""GitHub Action entrypoint for AI Decision Platform.

Runs the decision pipeline on a single customer message and writes
outputs in the GitHub Actions format.
"""

import json
import os
import sys

def write_output(name: str, value: str) -> None:
    output_file = os.environ.get("GITHUB_OUTPUT", "")
    if output_file:
        with open(output_file, "a") as f:
            if "\n" in value:
                import uuid
                delimiter = f"ghadelimiter_{uuid.uuid4()}"
                f.write(f"{name}<<{delimiter}\n{value}\n{delimiter}\n")
            else:
                f.write(f"{name}={value}\n")
    else:
        print(f"::set-output name={name}::{value}")


def main() -> None:
    args = sys.argv[1:]
    if len(args) < 9:
        print("::error::Missing required arguments")
        sys.exit(1)

    issue_text = args[0]
    customer_tier = args[1]
    channel = args[2]
    confidence_threshold = float(args[3])
    pii_redaction = args[4].lower() == "true"
    injection_detection = args[5].lower() == "true"
    embedding_backend = args[6]
    model_backend = args[7]
    output_format = args[8]

    # ── Configure environment ───────────────────────────────────────
    os.environ.setdefault("APP_ENV", "action")
    os.environ["PII_REDACTION_ENABLED"] = str(pii_redaction).lower()
    os.environ["CONFIDENCE_THRESHOLD"] = str(confidence_threshold)
    os.environ["EMBEDDING_BACKEND"] = embedding_backend
    os.environ["AUTH_ENABLED"] = "false"
    os.environ["RATE_LIMIT_ENABLED"] = "false"
    os.environ["USE_REDIS"] = "false"
    os.environ["USE_POSTGRES"] = "false"
    os.environ["METRICS_ENABLED"] = "false"

    # ── PII redaction ───────────────────────────────────────────────
    pii_detected = False
    redacted_text = issue_text
    if pii_redaction:
        try:
            from app.utils.pii_redaction import redact_pii
            redacted_text = redact_pii(issue_text)
            pii_detected = redacted_text != issue_text
        except Exception as exc:
            print(f"::warning::PII redaction failed: {exc}")

    # ── Prompt injection detection ──────────────────────────────────
    injection_detected = False
    if injection_detection:
        try:
            from app.security.prompt_injection import check_prompt_injection
            result = check_prompt_injection(redacted_text)
            injection_detected = bool(result)
            if injection_detected:
                print("::warning::Prompt injection detected in input")
                write_output("decision", "escalate")
                write_output("intent", "injection_detected")
                write_output("confidence", "0.0")
                write_output("confidence_signals", "{}")
                write_output("pii_detected", str(pii_detected).lower())
                write_output("injection_detected", "true")
                write_output("policy_override", "injection_blocked")
                result_obj = {
                    "decision": "escalate",
                    "intent": "injection_detected",
                    "confidence": 0.0,
                    "pii_detected": pii_detected,
                    "injection_detected": True,
                    "policy_override": "injection_blocked",
                }
                write_output("result_json", json.dumps(result_obj))
                return
        except Exception as exc:
            print(f"::warning::Injection detection failed: {exc}")

    # ── Intent routing ──────────────────────────────────────────────
    intent = "unknown"
    route_confidence = 0.0
    try:
        from app.services.routing import RoutingService
        router = RoutingService()
        route_result = router.classify(redacted_text)
        intent = route_result.get("intent", "unknown")
        route_confidence = route_result.get("confidence", 0.0)
    except Exception as exc:
        print(f"::warning::Routing failed: {exc}")

    # ── Confidence scoring ──────────────────────────────────────────
    evidence_quality = 0.0
    try:
        from app.services.retrieval import RetrievalService
        retriever = RetrievalService()
        chunks = retriever.search(redacted_text, top_k=3)
        if chunks:
            evidence_quality = max(c.get("score", 0.0) for c in chunks)
    except Exception:
        pass

    escalation_risk = 0.0
    try:
        from app.utils.confidence import compute_confidence
        conf = compute_confidence(
            route_confidence=route_confidence,
            evidence_quality=evidence_quality,
            escalation_risk=0.0,
            ood_score=0.0,
            contradiction_flag=0.0,
        )
        final_confidence = conf if isinstance(conf, float) else conf.get("final", route_confidence)
    except Exception:
        final_confidence = route_confidence

    signals = {
        "route_confidence": round(route_confidence, 4),
        "evidence_quality": round(evidence_quality, 4),
        "escalation_risk": round(escalation_risk, 4),
        "ood_score": 0.0,
        "contradiction_flag": 0.0,
    }

    # ── Policy gate ─────────────────────────────────────────────────
    policy_override = None

    HIGH_RISK_TERMS = {"breach", "lawsuit", "fraud", "legal threat", "security incident"}
    lower_text = redacted_text.lower()
    for term in HIGH_RISK_TERMS:
        if term in lower_text:
            policy_override = f"policy_high_risk:{term}"
            break

    # ── Decision ────────────────────────────────────────────────────
    if policy_override:
        decision = "escalate"
    elif final_confidence < confidence_threshold:
        decision = "abstain"
    else:
        decision = "auto_respond"

    # ── Write outputs ───────────────────────────────────────────────
    write_output("decision", decision)
    write_output("intent", intent)
    write_output("confidence", str(round(final_confidence, 4)))
    write_output("confidence_signals", json.dumps(signals))
    write_output("pii_detected", str(pii_detected).lower())
    write_output("injection_detected", str(injection_detected).lower())
    write_output("policy_override", policy_override or "null")

    result_obj = {
        "decision": decision,
        "intent": intent,
        "confidence": round(final_confidence, 4),
        "confidence_signals": signals,
        "pii_detected": pii_detected,
        "injection_detected": injection_detected,
        "policy_override": policy_override,
        "customer_tier": customer_tier,
        "channel": channel,
    }
    result_json = json.dumps(result_obj, indent=2)
    write_output("result_json", result_json)

    # ── Console summary ─────────────────────────────────────────────
    if output_format == "summary":
        icon = {"auto_respond": "✅", "abstain": "🤷", "escalate": "🚨"}.get(decision, "❓")
        print(f"\n{'='*60}")
        print(f"  {icon}  Decision: {decision.upper()}")
        print(f"     Intent:     {intent}")
        print(f"     Confidence: {final_confidence:.1%}")
        print(f"     PII found:  {pii_detected}")
        print(f"     Policy:     {policy_override or 'none'}")
        print(f"{'='*60}\n")
    else:
        print(result_json)


if __name__ == "__main__":
    main()
