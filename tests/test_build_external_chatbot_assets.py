from __future__ import annotations

import csv
import json
from pathlib import Path

from scripts.build_external_chatbot_assets import (
    dedupe_pairs,
    parse_abcd_pairs,
    parse_twitter_pairs,
    to_retrieval_chunks,
    write_retrieval_jsonl,
    write_style_jsonl,
)


def test_parse_twitter_pairs_and_write_outputs(tmp_path: Path) -> None:
    csv_path = tmp_path / 'twcs.csv'
    with csv_path.open('w', encoding='utf-8', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=['tweet_id', 'in_response_to_tweet_id', 'inbound', 'text'])
        writer.writeheader()
        writer.writerow(
            {
                'tweet_id': '1',
                'in_response_to_tweet_id': '',
                'inbound': 'true',
                'text': 'I was charged twice and need help',
            }
        )
        writer.writerow(
            {
                'tweet_id': '2',
                'in_response_to_tweet_id': '1',
                'inbound': 'false',
                'text': 'Sorry about this. We can refund the duplicate charge today.',
            }
        )

    pairs = parse_twitter_pairs(csv_path)
    assert len(pairs) == 1

    deduped = dedupe_pairs(pairs)
    style_path = tmp_path / 'style.jsonl'
    retrieval_path = tmp_path / 'retrieval.jsonl'

    style_count = write_style_jsonl(style_path, deduped, max_rows=100)
    retrieval_rows = to_retrieval_chunks(deduped, tenant_id='org_demo', max_rows=100)
    retrieval_count = write_retrieval_jsonl(retrieval_path, retrieval_rows)

    assert style_count == 1
    assert retrieval_count == 1


def test_parse_abcd_pairs(tmp_path: Path) -> None:
    abcd_path = tmp_path / 'abcd.json'
    payload = [
        {
            'dialogue': [
                {'role': 'user', 'text': 'My account is locked and I cannot login'},
                {'role': 'assistant', 'text': 'Please verify identity and I will send a reset link.'},
            ]
        }
    ]
    abcd_path.write_text(json.dumps(payload), encoding='utf-8')

    pairs = parse_abcd_pairs(abcd_path)
    assert len(pairs) == 1
    assert pairs[0].channel == 'chat'
    assert 'account is locked' in pairs[0].customer_text.lower()
