package assist

default decision := {
  "allow_auto_response": true,
  "final_decision": "recommend",
  "reason_codes": []
}

high_risk_terms := {"breach", "lawsuit", "fraud", "legal threat", "security incident"}

contains_high_risk {
  some t in high_risk_terms
  contains(lower(input.issue_text), t)
}

too_low_conf {
  input.final_confidence < input.threshold
}

too_high_escalation {
  input.escalation_prob >= input.max_auto_escalation
}

decision := {
  "allow_auto_response": false,
  "final_decision": "escalate",
  "reason_codes": ["policy_high_risk"]
} if {
  contains_high_risk
}

decision := {
  "allow_auto_response": false,
  "final_decision": "abstain",
  "reason_codes": ["low_confidence"]
} if {
  not contains_high_risk
  too_low_conf
}

decision := {
  "allow_auto_response": false,
  "final_decision": "abstain",
  "reason_codes": ["high_escalation_risk"]
} if {
  not contains_high_risk
  not too_low_conf
  too_high_escalation
}

