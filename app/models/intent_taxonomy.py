"""Expanded intent taxonomy for the decision platform.

Combines intents from three reference datasets:
  1. ABCD (Action-Based Conversations Dataset) – 55 subflows in e-commerce
  2. Twitter Customer Support – social media brand interactions
  3. Bitext Customer Support LLM Training Dataset – 27 intents across 10 categories

This module provides:
  - A canonical intent catalog with metadata (category, description, risk level, keywords)
  - Intent detection helpers for heuristic routing
  - Mapping utilities from legacy 5-label route set to the expanded taxonomy
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class IntentDefinition:
    """Single intent in the canonical catalog."""
    intent_id: str
    category: str
    description: str
    risk_level: str
    keywords: tuple[str, ...]
    escalation_hint: float


INTENT_CATALOG: list[IntentDefinition] = [
    IntentDefinition('create_account', 'ACCOUNT', 'Customer wants to create a new account', 'low',
                     ('create account', 'sign up', 'register', 'new account', 'open account'), 0.05),
    IntentDefinition('delete_account', 'ACCOUNT', 'Customer wants to delete their account', 'medium',
                     ('delete account', 'close account', 'remove account', 'deactivate'), 0.25),
    IntentDefinition('edit_account', 'ACCOUNT', 'Customer wants to edit account details', 'low',
                     ('edit account', 'update account', 'change details', 'modify account', 'update profile'), 0.05),
    IntentDefinition('switch_account', 'ACCOUNT', 'Customer wants to switch between accounts', 'low',
                     ('switch account', 'change account', 'different account', 'other account'), 0.05),
    IntentDefinition('recover_password', 'ACCOUNT', 'Customer needs password recovery', 'medium',
                     ('password', 'forgot password', 'reset password', 'locked out', 'login', 'cant login', "can't log in"), 0.15),
    IntentDefinition('registration_problems', 'ACCOUNT', 'Customer has trouble registering', 'medium',
                     ('registration', 'signup error', 'cannot register', "can't sign up", 'registration failed'), 0.15),

    IntentDefinition('place_order', 'ORDER', 'Customer wants to place an order', 'low',
                     ('place order', 'buy', 'purchase', 'order', 'add to cart', 'checkout'), 0.05),
    IntentDefinition('cancel_order', 'ORDER', 'Customer wants to cancel an order', 'medium',
                     ('cancel order', 'cancel my order', 'cancel purchase', 'stop order', 'void order',
                      'cancel my subscription', 'cancel subscription', 'cancel'), 0.15),
    IntentDefinition('change_order', 'ORDER', 'Customer wants to change an existing order', 'medium',
                     ('change order', 'modify order', 'update order', 'edit order', 'amend order'), 0.15),
    IntentDefinition('track_order', 'ORDER', 'Customer wants to track their order', 'low',
                     ('track order', 'where is my order', 'order status', 'shipping status', 'delivery status'), 0.05),

    IntentDefinition('check_payment_methods', 'PAYMENT', 'Customer asks about payment methods', 'low',
                     ('payment method', 'how to pay', 'accepted payments', 'pay with', 'credit card', 'debit card'), 0.05),
    IntentDefinition('payment_issue', 'PAYMENT', 'Customer has a payment problem', 'high',
                     ('payment issue', 'payment failed', 'payment error', 'declined', 'charged twice', 'double charge',
                      'overcharged', 'incorrect charge'), 0.35),

    IntentDefinition('check_refund_policy', 'REFUND', 'Customer asks about refund policy', 'low',
                     ('refund policy', 'return policy', 'can i get a refund', 'refund eligibility'), 0.05),
    IntentDefinition('get_refund', 'REFUND', 'Customer requests a refund', 'medium',
                     ('refund', 'money back', 'get refund', 'want refund', 'request refund', 'reimburse'), 0.20),
    IntentDefinition('track_refund', 'REFUND', 'Customer wants to track refund status', 'low',
                     ('track refund', 'refund status', 'where is my refund', 'refund pending'), 0.05),

    IntentDefinition('delivery_options', 'SHIPPING', 'Customer asks about delivery options', 'low',
                     ('delivery option', 'shipping option', 'shipping method', 'express', 'standard delivery'), 0.05),
    IntentDefinition('delivery_period', 'SHIPPING', 'Customer asks about delivery time', 'low',
                     ('delivery time', 'how long', 'when will', 'estimated delivery', 'arrival'), 0.05),
    IntentDefinition('change_shipping_address', 'SHIPPING', 'Customer wants to change shipping address', 'medium',
                     ('change address', 'shipping address', 'wrong address', 'update address', 'different address'), 0.10),
    IntentDefinition('set_up_shipping_address', 'SHIPPING', 'Customer wants to set up shipping address', 'low',
                     ('set up address', 'add address', 'new address', 'setup shipping'), 0.05),
    IntentDefinition('shipping_delay', 'SHIPPING', 'Customer complains about shipping delay', 'medium',
                     ('delay', 'late', 'delayed', 'shipping delay', 'not arrived', 'lost package', 'carrier'), 0.20),

    IntentDefinition('check_invoice', 'INVOICE', 'Customer wants to check an invoice', 'low',
                     ('check invoice', 'view invoice', 'invoice details', 'billing statement'), 0.05),
    IntentDefinition('get_invoice', 'INVOICE', 'Customer wants to get/download an invoice', 'low',
                     ('get invoice', 'download invoice', 'send invoice', 'invoice copy', 'receipt'), 0.05),

    IntentDefinition('check_cancellation_fee', 'CANCELLATION_FEE', 'Customer asks about cancellation fees', 'low',
                     ('cancellation fee', 'cancel fee', 'penalty', 'early termination', 'cancellation charge'), 0.10),

    IntentDefinition('complaint', 'FEEDBACK', 'Customer files a complaint', 'high',
                     ('complaint', 'unhappy', 'dissatisfied', 'terrible', 'worst', 'angry', 'frustrated',
                      'unacceptable', 'horrible', 'disgusted'), 0.40),
    IntentDefinition('review', 'FEEDBACK', 'Customer leaves a review', 'low',
                     ('review', 'feedback', 'rate', 'experience', 'suggestion'), 0.05),

    IntentDefinition('newsletter_subscription', 'NEWSLETTER', 'Customer wants to manage newsletter', 'low',
                     ('newsletter', 'subscribe', 'unsubscribe', 'mailing list', 'email list'), 0.05),

    IntentDefinition('contact_customer_service', 'CONTACT', 'Customer wants to contact support', 'low',
                     ('contact', 'speak to', 'talk to', 'reach', 'call', 'customer service', 'support line'), 0.10),
    IntentDefinition('contact_human_agent', 'CONTACT', 'Customer wants a human agent', 'medium',
                     ('human', 'real person', 'agent', 'representative', 'escalate', 'manager', 'supervisor'), 0.45),

    IntentDefinition('technical_issue', 'TECHNICAL', 'Customer reports a technical issue', 'medium',
                     ('error', 'bug', 'crash', 'not working', 'broken', 'glitch', 'failed', 'issue', 'problem'), 0.20),

    IntentDefinition('general_inquiry', 'GENERAL', 'General support inquiry', 'low',
                     ('help', 'support', 'question', 'information', 'how to', 'what is'), 0.05),
]

INTENT_BY_ID: dict[str, IntentDefinition] = {d.intent_id: d for d in INTENT_CATALOG}
INTENTS_BY_CATEGORY: dict[str, list[IntentDefinition]] = {}
for _d in INTENT_CATALOG:
    INTENTS_BY_CATEGORY.setdefault(_d.category, []).append(_d)

ALL_INTENT_LABELS: list[str] = [d.intent_id for d in INTENT_CATALOG]
ALL_CATEGORIES: list[str] = sorted(INTENTS_BY_CATEGORY.keys())


LEGACY_TO_EXPANDED: dict[str, list[str]] = {
    'refund_duplicate_charge': ['payment_issue', 'get_refund', 'check_refund_policy'],
    'account_access_recovery': ['recover_password', 'registration_problems', 'edit_account'],
    'shipping_delay_resolution': ['shipping_delay', 'delivery_period', 'track_order'],
    'technical_bug_triage': ['technical_issue', 'complaint'],
    'general_support_triage': ['general_inquiry', 'contact_customer_service'],
}

EXPANDED_TO_LEGACY: dict[str, str] = {}
for _legacy, _expanded_list in LEGACY_TO_EXPANDED.items():
    for _expanded in _expanded_list:
        EXPANDED_TO_LEGACY[_expanded] = _legacy


def map_to_legacy_route(intent_id: str) -> str:
    """Map an expanded intent ID back to the nearest legacy 5-label route."""
    return EXPANDED_TO_LEGACY.get(intent_id, 'general_support_triage')


def detect_intents_heuristic(text: str, *, top_k: int = 3) -> list[tuple[str, float]]:
    """Simple keyword-based intent detection for heuristic routing.

    Returns sorted list of (intent_id, score) for up to *top_k* intents.
    """
    txt = text.lower()
    scored: list[tuple[str, float]] = []

    for defn in INTENT_CATALOG:
        score = defn.escalation_hint * 0.1
        for kw in defn.keywords:
            if kw in txt:
                score += 1.2
        if score > 0.15:
            scored.append((defn.intent_id, round(score, 4)))

    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[:top_k]


def get_category(intent_id: str) -> str:
    """Return the parent category for an intent ID, or 'GENERAL' if unknown."""
    defn = INTENT_BY_ID.get(intent_id)
    return defn.category if defn else 'GENERAL'


def get_risk_level(intent_id: str) -> str:
    """Return the risk level for an intent ID, or 'medium' if unknown."""
    defn = INTENT_BY_ID.get(intent_id)
    return defn.risk_level if defn else 'medium'


def get_escalation_hint(intent_id: str) -> float:
    """Return the base escalation hint for an intent ID."""
    defn = INTENT_BY_ID.get(intent_id)
    return defn.escalation_hint if defn else 0.10
