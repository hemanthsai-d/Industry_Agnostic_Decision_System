"""Download the Bitext Customer Support LLM Chatbot Training Dataset from HuggingFace.

Uses httpx streaming to download the CSV in chunks, keeping peak memory well
under 100 MB.  The full CSV is ~19 MB (26 872 rows).

Usage:
    python -m scripts.download_bitext_dataset [--output artifacts/datasets/bitext_customer_support.csv]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import httpx

_HF_DATASET_URL = (
    'https://huggingface.co/datasets/bitext/'
    'Bitext-customer-support-llm-chatbot-training-dataset/'
    'resolve/main/Bitext_Sample_Customer_Support_Training_Dataset_27K_responses-v11.csv'
)

_CHUNK_SIZE = 64 * 1024


def download(url: str, dest: Path, *, timeout: float = 120.0) -> int:
    """Stream-download *url* to *dest*; return bytes written."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    with httpx.stream('GET', url, follow_redirects=True, timeout=timeout) as resp:
        resp.raise_for_status()
        total = resp.headers.get('content-length')
        total_mb = f'{int(total) / 1_048_576:.1f} MB' if total else 'unknown size'
        print(f'Downloading Bitext dataset ({total_mb}) → {dest}')
        with dest.open('wb') as fh:
            for chunk in resp.iter_bytes(chunk_size=_CHUNK_SIZE):
                fh.write(chunk)
                written += len(chunk)
    return written


def main() -> None:
    parser = argparse.ArgumentParser(description='Download Bitext customer support dataset.')
    parser.add_argument(
        '--output',
        default='artifacts/datasets/bitext_customer_support.csv',
        help='Destination CSV path.',
    )
    parser.add_argument(
        '--url',
        default=_HF_DATASET_URL,
        help='Override dataset URL (for mirrors or local testing).',
    )
    args = parser.parse_args()

    dest = Path(args.output).expanduser()
    if dest.exists():
        print(f'Dataset already exists at {dest} ({dest.stat().st_size / 1_048_576:.1f} MB). Skipping download.')
        print('  (delete the file and re-run to force a fresh download)')
        sys.exit(0)

    try:
        size = download(args.url, dest)
    except httpx.HTTPStatusError as exc:
        print(f'HTTP error: {exc.response.status_code} — {exc.request.url}', file=sys.stderr)
        sys.exit(1)
    except httpx.TransportError as exc:
        print(f'Network error: {exc}', file=sys.stderr)
        sys.exit(1)

    print(f'Done — {size / 1_048_576:.1f} MB written to {dest}')


if __name__ == '__main__':
    main()
