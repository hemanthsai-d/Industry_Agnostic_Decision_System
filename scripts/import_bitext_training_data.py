"""Import Bitext intent training data into the decision platform database.

Reads intent_training_pairs.jsonl (produced by build_external_chatbot_assets.py)
and populates:
  - evaluation_daily_dataset  → labeled evaluation rows with real customer text
  - inference_requests        → real issue text for the inference pipeline
  - inference_results         → with detected_intent + detected_category filled
  - dataset_imports           → audit trail of the import

Memory-safe: processes the JSONL in streaming 1 000-row batches.

Usage:
    python -m scripts.import_bitext_training_data [--reset]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID, uuid4, uuid5

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.core.config import get_settings
from app.models.intent_taxonomy import (
    INTENT_CATALOG,
    get_escalation_hint,
    map_to_legacy_route,
)
from app.storage.postgres_store import to_psycopg_dsn


TENANT_ID = 'org_demo'
SECTION_MAP: dict[str, str] = {
    'ACCOUNT': 'accounts',
    'ORDER': 'shipping',
    'PAYMENT': 'billing',
    'REFUND': 'billing',
    'SHIPPING_ADDRESS': 'shipping',
    'DELIVERY': 'shipping',
    'INVOICE': 'billing',
    'CANCELLATION_FEE': 'billing',
    'FEEDBACK': 'general',
    'NEWSLETTER': 'general',
    'CONTACT': 'general',
}
KNOWN_INTENTS = {idef.intent_id for idef in INTENT_CATALOG}

BATCH_SIZE = 1_000
IMPORT_SOURCE = 'bitext'

_NS = UUID('a3b2c1d0-e5f6-7890-abcd-ef1234567890')


def _deterministic_uuid(text: str) -> UUID:
    """Stable UUID for a given instruction string (idempotent imports)."""
    return uuid5(_NS, text)


def _rand(lo: float, hi: float) -> float:
    return round(random.uniform(lo, hi), 4)


def _section_for(category: str) -> str:
    return SECTION_MAP.get(category.upper().strip(), 'general')


def _risk_for(intent: str) -> str:
    """Derive risk level from the taxonomy or fallback."""
    for idef in INTENT_CATALOG:
        if idef.intent_id == intent:
            return idef.risk_level
    return 'medium'


def iter_intent_pairs(path: Path):
    """Yield dicts from the intent_training_pairs JSONL, one at a time."""
    with path.open('r', encoding='utf-8') as fh:
        for line in fh:
            raw = line.strip()
            if not raw:
                continue
            yield json.loads(raw)


def reset_bitext_data(conn: psycopg.Connection) -> None:
    """Remove all previously imported Bitext rows."""
    with conn.cursor() as cur:
        cur.execute("DELETE FROM evaluation_daily_dataset WHERE source = 'bitext';")
        cur.execute("DELETE FROM inference_results WHERE request_id IN (SELECT request_id FROM inference_requests WHERE context->>'import_source' = 'bitext');")
        cur.execute("DELETE FROM handoffs WHERE request_id IN (SELECT request_id FROM inference_requests WHERE context->>'import_source' = 'bitext');")
        cur.execute("DELETE FROM inference_requests WHERE context->>'import_source' = 'bitext';")
        cur.execute("DELETE FROM dataset_imports WHERE dataset_source = 'bitext';")
    conn.commit()
    print('  Bitext data reset complete.')


def upsert_missing_intents(conn: psycopg.Connection, intents_seen: set[str]) -> int:
    """Insert any Bitext intents missing from intent_taxonomy."""
    inserted = 0
    with conn.cursor() as cur:
        cur.execute("SELECT intent_id FROM intent_taxonomy;")
        existing = {row['intent_id'] for row in cur.fetchall()}
        for intent_id in sorted(intents_seen - existing):
            cur.execute(
                """
                INSERT INTO intent_taxonomy (intent_id, category, description, risk_level, keywords, escalation_hint)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (intent_id) DO NOTHING;
                """,
                (
                    intent_id,
                    'GENERAL',
                    f'Auto-imported from Bitext: {intent_id}',
                    'medium',
                    Jsonb([intent_id.replace('_', ' ')]),
                    0.10,
                ),
            )
            inserted += 1
    conn.commit()
    return inserted


def import_batch(
    conn: psycopg.Connection,
    rows: list[dict],
    window_start: date,
    window_end: date,
) -> dict[str, int]:
    """Import a batch of intent training pairs into the database."""
    stats: Counter[str] = Counter()
    window_days = (window_end - window_start).days + 1

    with conn.cursor() as cur:
        for row in rows:
            instruction = row.get('instruction', '').strip()
            response = row.get('response', '').strip()
            intent = row.get('intent', '').strip()
            category = row.get('category', '').strip()
            flags = row.get('flags', '').strip()

            if not instruction or not intent:
                stats['skipped'] += 1
                continue

            request_id = _deterministic_uuid(instruction)
            section = _section_for(category)
            risk_level = _risk_for(intent)
            route = map_to_legacy_route(intent) if intent in KNOWN_INTENTS else 'general_support_triage'
            escalation_hint = get_escalation_hint(intent)

            base_confidence = _rand(0.65, 0.95)
            escalation_prob = round(
                min(1.0, max(0.0, escalation_hint + _rand(-0.05, 0.10))), 4
            )
            route_prob = _rand(0.60, 0.95)

            if escalation_prob >= 0.45:
                decision = 'escalate'
            elif base_confidence < 0.70:
                decision = 'abstain'
            else:
                decision = 'recommend'

            eval_date = window_start + timedelta(days=random.randint(0, window_days - 1))
            ts = datetime.combine(eval_date, datetime.min.time(), tzinfo=timezone.utc) + timedelta(
                hours=random.randint(8, 20), minutes=random.randint(0, 59)
            )

            is_route_correct = random.random() < 0.88
            is_escalation_actual = escalation_prob >= 0.30
            is_escalation_pred = escalation_prob >= 0.35

            resolution_range = {'low': (30, 180), 'medium': (60, 360), 'high': (120, 600)}
            res_lo, res_hi = resolution_range.get(risk_level, (60, 360))
            resolution_seconds = random.randint(res_lo, res_hi)

            cur.execute(
                """
                INSERT INTO evaluation_daily_dataset (
                  eval_date, request_id, tenant_id, section, model_variant,
                  predicted_decision, predicted_route, predicted_route_prob,
                  escalation_prob, final_confidence,
                  ground_truth_decision, ground_truth_route,
                  is_route_correct, is_escalation_pred, is_escalation_actual,
                  issue_token_count, resolution_seconds, source
                ) VALUES (
                  %s, %s, %s, %s, 'primary',
                  %s, %s, %s, %s, %s,
                  %s, %s,
                  %s, %s, %s,
                  %s, %s, 'bitext'
                )
                ON CONFLICT DO NOTHING;
                """,
                (
                    eval_date, request_id, TENANT_ID, section,
                    decision, route, route_prob,
                    escalation_prob, base_confidence,
                    decision, route if is_route_correct else 'general_support_triage',
                    is_route_correct, is_escalation_pred, is_escalation_actual,
                    len(instruction.split()), resolution_seconds,
                ),
            )
            stats['eval_rows'] += 1

            cur.execute(
                """
                INSERT INTO inference_requests (
                  request_id, tenant_id, section, issue_text, risk_level, context, created_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (request_id) DO NOTHING;
                """,
                (
                    request_id, TENANT_ID, section,
                    instruction, risk_level,
                    Jsonb({'import_source': 'bitext', 'intent': intent, 'category': category, 'flags': flags}),
                    ts,
                ),
            )
            stats['inf_requests'] += 1

            cur.execute(
                """
                INSERT INTO inference_results (
                  request_id, decision, top_resolution_path, top_resolution_prob,
                  escalation_prob, final_confidence, trace_id, policy_result,
                  model_variant, detected_intent, detected_category, created_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'primary', %s, %s, %s)
                ON CONFLICT (request_id) DO NOTHING;
                """,
                (
                    request_id, decision, route, route_prob,
                    escalation_prob, base_confidence,
                    f'bitext-{hashlib.md5(instruction.encode()).hexdigest()[:12]}',
                    Jsonb({'import_source': 'bitext', 'intent': intent}),
                    intent, category, ts,
                ),
            )
            stats['inf_results'] += 1

    conn.commit()
    return dict(stats)


def record_import(conn: psycopg.Connection, record_count: int, metadata: dict) -> None:
    """Write an audit row to dataset_imports."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO dataset_imports (dataset_source, dataset_version, record_count, import_type, imported_by, metadata)
            VALUES ('bitext', 'v11-27k', %s, 'intent_training', 'import_bitext_training_data', %s);
            """,
            (record_count, Jsonb(metadata)),
        )
    conn.commit()


def main() -> None:
    parser = argparse.ArgumentParser(description='Import Bitext intent training data into the decision DB.')
    parser.add_argument(
        '--jsonl',
        default='artifacts/datasets/intent_training_pairs.jsonl',
        help='Path to intent_training_pairs.jsonl.',
    )
    parser.add_argument('--window-days', type=int, default=28, help='Spread eval dates across this many days.')
    parser.add_argument('--reset', action='store_true', help='Remove previous Bitext import before re-importing.')
    parser.add_argument('--max-rows', type=int, default=20000, help='Max rows to import (0=unlimited).')
    args = parser.parse_args()

    path = Path(args.jsonl).expanduser()
    if not path.exists():
        print(f'JSONL file not found: {path}', file=sys.stderr)
        print('Run `make build-chatbot-assets` first to generate it from the Bitext CSV.', file=sys.stderr)
        sys.exit(1)

    settings = get_settings()
    dsn = to_psycopg_dsn(settings.postgres_dsn)
    conn = psycopg.connect(dsn, row_factory=dict_row)

    if args.reset:
        print('Resetting previous Bitext import...')
        reset_bitext_data(conn)

    end_date = datetime.now(timezone.utc).date() - timedelta(days=1)
    start_date = end_date - timedelta(days=args.window_days - 1)

    print(f'Importing Bitext training data ({start_date} → {end_date})...')

    total_stats: Counter[str] = Counter()
    intents_seen: set[str] = set()
    batch: list[dict] = []
    row_count = 0
    max_rows = args.max_rows if args.max_rows > 0 else float('inf')

    for pair in iter_intent_pairs(path):
        if row_count >= max_rows:
            break
        batch.append(pair)
        intents_seen.add(pair.get('intent', ''))
        row_count += 1

        if len(batch) >= BATCH_SIZE:
            stats = import_batch(conn, batch, start_date, end_date)
            for k, v in stats.items():
                total_stats[k] += v
            batch.clear()
            print(f'  ... {row_count} rows processed', end='\r')

    if batch:
        stats = import_batch(conn, batch, start_date, end_date)
        for k, v in stats.items():
            total_stats[k] += v

    intents_seen.discard('')
    new_intents = upsert_missing_intents(conn, intents_seen)

    record_import(conn, row_count, {
        'eval_rows': total_stats.get('eval_rows', 0),
        'inference_requests': total_stats.get('inf_requests', 0),
        'inference_results': total_stats.get('inf_results', 0),
        'new_intents': new_intents,
        'intents_seen': sorted(intents_seen),
        'window': f'{start_date.isoformat()} → {end_date.isoformat()}',
    })

    conn.close()

    print(f'\nBitext import complete:')
    print(f'  - evaluation_daily_dataset: {total_stats.get("eval_rows", 0)} rows')
    print(f'  - inference_requests:       {total_stats.get("inf_requests", 0)} rows')
    print(f'  - inference_results:        {total_stats.get("inf_results", 0)} rows')
    print(f'  - intent_taxonomy new:      {new_intents} intents')
    print(f'  - dataset_imports:          1 audit row')
    print(f'  - distinct intents:         {len(intents_seen)}')


if __name__ == '__main__':
    main()
