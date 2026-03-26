from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Iterable

from app.utils.text_normalization import normalize_support_text, tokenize_support_text


@dataclass(frozen=True)
class ConversationPair:
    source: str
    customer_text: str
    agent_text: str
    tone: str
    channel: str
    tags: tuple[str, ...]


@dataclass(frozen=True)
class RetrievalSeedChunk:
    tenant_id: str
    section: str
    chunk_id: str
    doc_id: str
    source: str
    updated_at: str
    text: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Build style and retrieval assets from external support datasets.')
    parser.add_argument('--abcd-path', default='', help='Path to ABCD dataset JSON/JSONL file (optional).')
    parser.add_argument('--twitter-csv', default='', help='Path to Twitter support CSV (optional).')
    parser.add_argument('--bitext-csv', default='', help='Path to Bitext customer support CSV (optional).')
    parser.add_argument(
        '--style-output',
        default='artifacts/datasets/style_examples.jsonl',
        help='Output path for style examples JSONL.',
    )
    parser.add_argument(
        '--retrieval-output',
        default='artifacts/datasets/retrieval_seed_chunks.jsonl',
        help='Output path for retrieval seed JSONL.',
    )
    parser.add_argument(
        '--intent-output',
        default='artifacts/datasets/intent_training_pairs.jsonl',
        help='Output path for intent-labeled training pairs JSONL.',
    )
    parser.add_argument('--tenant-id', default='org_demo', help='Tenant id for retrieval seeds.')
    parser.add_argument('--max-style-rows', type=int, default=8000)
    parser.add_argument('--max-retrieval-rows', type=int, default=4000)
    parser.add_argument('--max-intent-rows', type=int, default=20000)
    return parser.parse_args()


def _safe_str(value: Any) -> str:
    if value is None:
        return ''
    return str(value).strip()


def _detect_role(payload: dict[str, Any]) -> str:
    role = _safe_str(payload.get('role') or payload.get('speaker') or payload.get('author_role') or payload.get('author'))
    if role:
        role = role.lower()
        if any(tag in role for tag in ('agent', 'assistant', 'support', 'system')):
            return 'assistant'
        return 'user'

    inbound = payload.get('inbound')
    if isinstance(inbound, bool):
        return 'user' if inbound else 'assistant'

    return 'user'


def _normalize_tone(agent_text: str) -> str:
    txt = normalize_support_text(agent_text)
    if any(term in txt for term in ('sorry', 'apologize', 'understand', 'frustrating')):
        return 'empathetic'
    if any(term in txt for term in ('please', 'kindly', 'verify', 'confirm')):
        return 'professional'
    return 'friendly'


def _infer_section(text: str) -> str:
    txt = normalize_support_text(text)
    if any(term in txt for term in ('refund', 'charged', 'billing', 'invoice', 'payment')):
        return 'billing'
    if any(term in txt for term in ('password', 'login', 'account', 'locked', 'access')):
        return 'accounts'
    if any(term in txt for term in ('shipping', 'delivery', 'carrier', 'package', 'order')):
        return 'shipping'
    if any(term in txt for term in ('error', 'bug', 'crash', 'failed', 'issue')):
        return 'technical'
    return 'general'


def _iter_json_records(path: Path) -> Iterable[Any]:
    if path.suffix.lower() == '.jsonl':
        with path.open('r', encoding='utf-8') as handle:
            for line in handle:
                raw = line.strip()
                if not raw:
                    continue
                try:
                    yield json.loads(raw)
                except json.JSONDecodeError:
                    continue
        return

    with path.open('r', encoding='utf-8') as handle:
        payload = json.load(handle)

    if isinstance(payload, list):
        for item in payload:
            yield item
    else:
        yield payload


def _extract_turns(record: Any) -> list[dict[str, str]]:
    turns: list[dict[str, str]] = []

    def visit(node: Any) -> None:
        if isinstance(node, dict):
            text = _safe_str(node.get('text') or node.get('utterance') or node.get('message') or node.get('response'))
            if text:
                turns.append({'role': _detect_role(node), 'text': text})

            for key in ('dialogue', 'dialog', 'turns', 'messages', 'conversation', 'chat'):
                value = node.get(key)
                if isinstance(value, list):
                    for item in value:
                        visit(item)
            return

        if isinstance(node, list):
            for item in node:
                visit(item)

    visit(record)
    return turns


def _conversation_pairs_from_turns(turns: list[dict[str, str]], source: str, channel: str) -> list[ConversationPair]:
    pairs: list[ConversationPair] = []
    last_user_text = ''

    for turn in turns:
        role = _safe_str(turn.get('role')).lower()
        text = _safe_str(turn.get('text'))
        if not text:
            continue

        if role == 'user':
            last_user_text = text
            continue

        if role == 'assistant' and last_user_text:
            tone = _normalize_tone(text)
            tags = tuple(sorted(set(tokenize_support_text(last_user_text)) & {'refund', 'login', 'shipping', 'error'}))
            pairs.append(
                ConversationPair(
                    source=source,
                    customer_text=last_user_text,
                    agent_text=text,
                    tone=tone,
                    channel=channel,
                    tags=tags,
                )
            )
            last_user_text = ''

    return pairs


def parse_abcd_pairs(path: Path) -> list[ConversationPair]:
    pairs: list[ConversationPair] = []
    for record in _iter_json_records(path):
        turns = _extract_turns(record)
        if not turns:
            continue
        pairs.extend(_conversation_pairs_from_turns(turns, source='abcd', channel='chat'))
    return pairs


def _parse_bool(value: str) -> bool | None:
    txt = _safe_str(value).lower()
    if txt in {'true', '1', 'yes'}:
        return True
    if txt in {'false', '0', 'no'}:
        return False
    return None


def parse_twitter_pairs(path: Path) -> list[ConversationPair]:
    pairs: list[ConversationPair] = []
    rows_by_id: dict[str, dict[str, str]] = {}

    with path.open('r', encoding='utf-8', newline='') as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            tweet_id = _safe_str(row.get('tweet_id') or row.get('id'))
            if not tweet_id:
                continue
            rows_by_id[tweet_id] = {k: _safe_str(v) for k, v in row.items()}

    for row in rows_by_id.values():
        parent_id = _safe_str(row.get('in_response_to_tweet_id'))
        if not parent_id:
            continue
        parent = rows_by_id.get(parent_id)
        if not parent:
            continue

        parent_text = _safe_str(parent.get('text'))
        reply_text = _safe_str(row.get('text'))
        if not parent_text or not reply_text:
            continue

        parent_inbound = _parse_bool(parent.get('inbound', ''))
        reply_inbound = _parse_bool(row.get('inbound', ''))
        if parent_inbound is not None and reply_inbound is not None:
            if not (parent_inbound and not reply_inbound):
                continue

        tone = _normalize_tone(reply_text)
        tags = tuple(sorted(set(tokenize_support_text(parent_text)) & {'refund', 'delay', 'shipping', 'account', 'password'}))
        pairs.append(
            ConversationPair(
                source='twitter_support',
                customer_text=parent_text,
                agent_text=reply_text,
                tone=tone,
                channel='social',
                tags=tags,
            )
        )

    return pairs


@dataclass(frozen=True)
class IntentTrainingPair:
    """A labeled training pair for intent classification."""
    instruction: str
    response: str
    intent: str
    category: str
    source: str
    flags: str = ''


_BITEXT_CATEGORY_MAP: dict[str, str] = {
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


def _bitext_category_to_section(category: str) -> str:
    return _BITEXT_CATEGORY_MAP.get(category.upper().strip(), 'general')


def _bitext_intent_to_tone(intent: str, flags: str) -> str:
    flags_lower = flags.lower() if flags else ''
    if 'W' in flags:
        return 'empathetic'
    if 'P' in flags:
        return 'professional'
    if 'Q' in flags:
        return 'friendly'
    if intent.lower() in ('complaint', 'review'):
        return 'empathetic'
    return 'professional'


def parse_bitext_pairs(path: Path) -> tuple[list[ConversationPair], list[IntentTrainingPair]]:
    """Parse Bitext customer-support CSV.

    Expected columns: flags, instruction, category, intent, response
    Returns conversation pairs + labeled intent training pairs.
    """
    conversation_pairs: list[ConversationPair] = []
    intent_pairs: list[IntentTrainingPair] = []

    with path.open('r', encoding='utf-8', newline='') as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            instruction = _safe_str(row.get('instruction'))
            response = _safe_str(row.get('response'))
            intent = _safe_str(row.get('intent'))
            category = _safe_str(row.get('category'))
            flags = _safe_str(row.get('flags'))

            if not instruction or not response:
                continue

            if intent:
                intent_pairs.append(IntentTrainingPair(
                    instruction=instruction,
                    response=response,
                    intent=intent,
                    category=category,
                    source='bitext',
                    flags=flags,
                ))

            section = _bitext_category_to_section(category)
            tone = _bitext_intent_to_tone(intent, flags)
            tags_set = set()
            if intent:
                tags_set.add(intent.lower())
            if category:
                tags_set.add(category.lower())

            conversation_pairs.append(ConversationPair(
                source='bitext',
                customer_text=instruction,
                agent_text=response,
                tone=tone,
                channel='chat',
                tags=tuple(sorted(tags_set)),
            ))

    return conversation_pairs, intent_pairs


def write_intent_jsonl(path: Path, rows: list[IntentTrainingPair], max_rows: int) -> int:
    """Write intent-labeled training pairs to JSONL format."""
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open('w', encoding='utf-8') as handle:
        for row in rows[:max_rows]:
            payload = {
                'instruction': row.instruction,
                'response': row.response,
                'intent': row.intent,
                'category': row.category,
                'source': row.source,
                'flags': row.flags,
            }
            handle.write(json.dumps(payload, ensure_ascii=True) + '\n')
            count += 1
    return count


def dedupe_pairs(pairs: list[ConversationPair]) -> list[ConversationPair]:
    deduped: list[ConversationPair] = []
    seen: set[tuple[str, str]] = set()

    for pair in pairs:
        key = (normalize_support_text(pair.customer_text), normalize_support_text(pair.agent_text))
        if not key[0] or not key[1] or key in seen:
            continue
        seen.add(key)
        deduped.append(pair)

    return deduped


def to_retrieval_chunks(
    pairs: list[ConversationPair],
    *,
    tenant_id: str,
    max_rows: int,
) -> list[RetrievalSeedChunk]:
    chunks: list[RetrievalSeedChunk] = []
    seen_text: set[str] = set()
    today = datetime.now(timezone.utc).date().isoformat()

    for index, pair in enumerate(pairs, start=1):
        if len(chunks) >= max_rows:
            break

        response_text = _safe_str(pair.agent_text)
        normalized = normalize_support_text(response_text)
        if len(normalized.split()) < 8 or normalized in seen_text:
            continue

        seen_text.add(normalized)
        section = _infer_section(pair.customer_text + ' ' + pair.agent_text)
        chunk_id = f'ext_{pair.source}_{index:06d}'
        doc_id = f'ext_{pair.source}_{section}_playbook'

        chunks.append(
            RetrievalSeedChunk(
                tenant_id=tenant_id,
                section=section,
                chunk_id=chunk_id,
                doc_id=doc_id,
                source=pair.source,
                updated_at=today,
                text=response_text,
            )
        )

    return chunks


def write_style_jsonl(path: Path, rows: list[ConversationPair], max_rows: int) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open('w', encoding='utf-8') as handle:
        for row in rows[:max_rows]:
            payload = {
                'source': row.source,
                'tone': row.tone,
                'channel': row.channel,
                'customer_text': row.customer_text,
                'agent_text': row.agent_text,
                'tags': list(row.tags),
            }
            handle.write(json.dumps(payload, ensure_ascii=True) + '\n')
            count += 1
    return count


def write_retrieval_jsonl(path: Path, rows: list[RetrievalSeedChunk]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open('w', encoding='utf-8') as handle:
        for row in rows:
            payload = {
                'tenant_id': row.tenant_id,
                'section': row.section,
                'chunk_id': row.chunk_id,
                'doc_id': row.doc_id,
                'source': row.source,
                'updated_at': row.updated_at,
                'text': row.text,
            }
            handle.write(json.dumps(payload, ensure_ascii=True) + '\n')
            count += 1
    return count


def main() -> None:
    args = parse_args()

    all_pairs: list[ConversationPair] = []
    all_intent_pairs: list[IntentTrainingPair] = []

    if args.abcd_path:
        abcd_file = Path(args.abcd_path).expanduser()
        if not abcd_file.exists():
            raise FileNotFoundError(f'ABCD path not found: {abcd_file}')
        all_pairs.extend(parse_abcd_pairs(abcd_file))

    if args.twitter_csv:
        twitter_file = Path(args.twitter_csv).expanduser()
        if not twitter_file.exists():
            raise FileNotFoundError(f'Twitter CSV path not found: {twitter_file}')
        all_pairs.extend(parse_twitter_pairs(twitter_file))

    if args.bitext_csv:
        bitext_file = Path(args.bitext_csv).expanduser()
        if not bitext_file.exists():
            raise FileNotFoundError(f'Bitext CSV path not found: {bitext_file}')
        bitext_conv_pairs, bitext_intent_pairs = parse_bitext_pairs(bitext_file)
        all_pairs.extend(bitext_conv_pairs)
        all_intent_pairs.extend(bitext_intent_pairs)

    if not all_pairs:
        raise ValueError('No conversation pairs extracted. Provide at least one valid input dataset file.')

    deduped = dedupe_pairs(all_pairs)
    retrieval_rows = to_retrieval_chunks(
        deduped,
        tenant_id=args.tenant_id,
        max_rows=max(1, int(args.max_retrieval_rows)),
    )

    style_output = Path(args.style_output).expanduser()
    retrieval_output = Path(args.retrieval_output).expanduser()
    intent_output = Path(args.intent_output).expanduser()

    style_count = write_style_jsonl(style_output, deduped, max_rows=max(1, int(args.max_style_rows)))
    retrieval_count = write_retrieval_jsonl(retrieval_output, retrieval_rows)

    intent_count = 0
    if all_intent_pairs:
        intent_count = write_intent_jsonl(intent_output, all_intent_pairs, max_rows=max(1, int(args.max_intent_rows)))

    print('External asset build complete.')
    print(f'- style_examples: {style_count} -> {style_output}')
    print(f'- retrieval_seed_chunks: {retrieval_count} -> {retrieval_output}')
    if intent_count:
        print(f'- intent_training_pairs: {intent_count} -> {intent_output}')


if __name__ == '__main__':
    main()
