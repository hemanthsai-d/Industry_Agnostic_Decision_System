from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import statistics
import sys
from typing import Any
from uuid import uuid4

import httpx
import psycopg

from app.core.config import get_settings
from app.storage.postgres_store import to_psycopg_dsn
from scripts.record_operational_control import record_control_event

CONTROL_TYPE_BY_MODE = {
    'load': 'load_test',
    'soak': 'soak_test',
    'failure': 'failure_test',
}


@dataclass
class ProbeResult:
    latency_ms: float
    status_code: int
    ok: bool
    error: str


def _is_success_status(status_code: int) -> bool:
    return 200 <= int(status_code) < 300


def _percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    if len(values) == 1:
        return values[0]
    rank = max(0, min(len(values) - 1, int(round((p / 100.0) * (len(values) - 1)))))
    return sorted(values)[rank]


async def _worker(
    *,
    worker_id: int,
    client: httpx.AsyncClient,
    base_url: str,
    token: str,
    tenant_id: str,
    section: str,
    mode: str,
    stop_at_monotonic: float,
    timeout_seconds: float,
    results: list[ProbeResult],
    lock: asyncio.Lock,
) -> None:
    while asyncio.get_running_loop().time() < stop_at_monotonic:
        issue_text = 'Customer charged twice and requests refund'
        if mode == 'failure':
            issue_text = 'Security breach lawsuit complaint with suspected fraud and urgent escalation'
        payload = {
            'request_id': str(uuid4()),
            'tenant_id': tenant_id,
            'section': section,
            'issue_text': issue_text,
            'risk_level': 'medium',
            'max_evidence_chunks': 5,
        }
        headers = {'Content-Type': 'application/json'}
        if token:
            headers['Authorization'] = f'Bearer {token}'

        start = asyncio.get_running_loop().time()
        try:
            response = await client.post(
                f'{base_url.rstrip("/")}/v1/assist/decide',
                json=payload,
                headers=headers,
                timeout=timeout_seconds,
            )
            latency_ms = (asyncio.get_running_loop().time() - start) * 1000.0
            ok = _is_success_status(response.status_code)
            err = ''
        except Exception as exc:  # pragma: no cover
            latency_ms = (asyncio.get_running_loop().time() - start) * 1000.0
            response = None
            ok = False
            err = str(exc)

        result = ProbeResult(
            latency_ms=latency_ms,
            status_code=response.status_code if response is not None else 0,
            ok=ok,
            error=err,
        )
        async with lock:
            results.append(result)


def _write_reports(
    *,
    json_path: Path,
    md_path: Path,
    report: dict[str, Any],
) -> None:
    json_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding='utf-8')

    status = 'PASS' if report['passed'] else 'FAIL'
    lines = [
        f'# Non-Functional Validation ({status})',
        '',
        f"- Generated at (UTC): {report['generated_at_utc']}",
        f"- Mode: {report['mode']}",
        f"- Base URL: {report['base_url']}",
        f"- Duration seconds: {report['duration_seconds']}",
        f"- Concurrency: {report['concurrency']}",
        '',
        '## Summary',
        f"- Total requests: {report['summary']['total_requests']}",
        f"- Success requests: {report['summary']['success_requests']}",
        f"- Error rate: {report['summary']['error_rate']:.4f}",
        f"- p50 latency ms: {report['summary']['p50_latency_ms']}",
        f"- p95 latency ms: {report['summary']['p95_latency_ms']}",
        '',
        '## Thresholds',
        f"- max_error_rate: {report['thresholds']['max_error_rate']}",
        f"- max_p95_latency_ms: {report['thresholds']['max_p95_latency_ms']}",
        '',
        '## Status Codes',
    ]
    for code, count in sorted(report['summary']['status_counts'].items(), key=lambda item: int(item[0])):
        lines.append(f'- {code}: {count}')
    lines.extend(['', '## Errors'])
    if report['errors']:
        lines.extend([f'- {item}' for item in report['errors']])
    else:
        lines.append('- none')
    md_path.write_text('\n'.join(lines) + '\n', encoding='utf-8')


async def run_probe(
    *,
    base_url: str,
    token: str,
    tenant_id: str,
    section: str,
    mode: str,
    duration_seconds: int,
    concurrency: int,
    timeout_seconds: float,
) -> list[ProbeResult]:
    stop_at = asyncio.get_running_loop().time() + float(duration_seconds)
    results: list[ProbeResult] = []
    lock = asyncio.Lock()
    async with httpx.AsyncClient() as client:
        tasks = [
            asyncio.create_task(
                _worker(
                    worker_id=i,
                    client=client,
                    base_url=base_url,
                    token=token,
                    tenant_id=tenant_id,
                    section=section,
                    mode=mode,
                    stop_at_monotonic=stop_at,
                    timeout_seconds=timeout_seconds,
                    results=results,
                    lock=lock,
                )
            )
            for i in range(max(1, concurrency))
        ]
        await asyncio.gather(*tasks)
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description='Run load/soak/failure probes against decision API.')
    parser.add_argument('--base-url', default='http://127.0.0.1:8000', help='API base URL.')
    parser.add_argument('--token', default='', help='Optional bearer token for protected endpoints.')
    parser.add_argument('--tenant-id', default='org_demo', help='Tenant id payload value.')
    parser.add_argument('--section', default='billing', help='Section payload value.')
    parser.add_argument('--mode', default='load', choices=['load', 'soak', 'failure'])
    parser.add_argument('--duration-seconds', type=int, default=60, help='Probe duration.')
    parser.add_argument('--concurrency', type=int, default=10, help='Number of concurrent workers.')
    parser.add_argument('--timeout-seconds', type=float, default=5.0, help='Per-request timeout.')
    parser.add_argument('--max-error-rate', type=float, default=0.02, help='Fail if observed error rate exceeds this.')
    parser.add_argument('--max-p95-latency-ms', type=float, default=1200.0, help='Fail if p95 exceeds this threshold.')
    parser.add_argument('--output-json', default='', help='Optional report JSON path.')
    parser.add_argument('--output-markdown', default='', help='Optional report markdown path.')
    parser.add_argument('--record-event', action='store_true', help='Record PASS/FAIL in operational_control_events.')
    parser.add_argument('--performed-by', default='', help='Required with --record-event.')
    parser.add_argument('--scope', default='global', help='Control scope for recorded event.')
    args = parser.parse_args()

    duration = max(5, int(args.duration_seconds))
    concurrency = max(1, int(args.concurrency))
    timeout_seconds = max(0.5, float(args.timeout_seconds))

    results = asyncio.run(
        run_probe(
            base_url=args.base_url,
            token=args.token.strip(),
            tenant_id=args.tenant_id.strip(),
            section=args.section.strip() or 'billing',
            mode=args.mode,
            duration_seconds=duration,
            concurrency=concurrency,
            timeout_seconds=timeout_seconds,
        )
    )

    latencies = [item.latency_ms for item in results]
    total = len(results)
    success = sum(1 for item in results if item.ok)
    errors = [item.error for item in results if item.error]
    status_counts = Counter(str(item.status_code) for item in results)
    error_rate = 0.0 if total == 0 else float(total - success) / float(total)
    p50 = _percentile(latencies, 50.0)
    p95 = _percentile(latencies, 95.0)
    mean = statistics.fmean(latencies) if latencies else None

    failures: list[str] = []
    if total == 0:
        failures.append('No requests were executed.')
    if error_rate > float(args.max_error_rate):
        failures.append(
            f'error_rate {error_rate:.4f} exceeded max_error_rate {float(args.max_error_rate):.4f}.'
        )
    if p95 is None or p95 > float(args.max_p95_latency_ms):
        failures.append(
            f'p95_latency_ms {p95 if p95 is not None else "n/a"} exceeded max_p95_latency_ms '
            f'{float(args.max_p95_latency_ms):.2f}.'
        )

    passed = len(failures) == 0
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    json_path = Path(args.output_json) if args.output_json.strip() else Path(
        f'artifacts/reports/nonfunctional_{args.mode}_{stamp}.json'
    )
    md_path = Path(args.output_markdown) if args.output_markdown.strip() else Path(
        f'artifacts/reports/nonfunctional_{args.mode}_{stamp}.md'
    )
    report = {
        'generated_at_utc': datetime.now(timezone.utc).isoformat(),
        'mode': args.mode,
        'base_url': args.base_url,
        'duration_seconds': duration,
        'concurrency': concurrency,
        'thresholds': {
            'max_error_rate': float(args.max_error_rate),
            'max_p95_latency_ms': float(args.max_p95_latency_ms),
        },
        'summary': {
            'total_requests': total,
            'success_requests': success,
            'error_rate': error_rate,
            'p50_latency_ms': round(p50, 2) if p50 is not None else None,
            'p95_latency_ms': round(p95, 2) if p95 is not None else None,
            'mean_latency_ms': round(mean, 2) if mean is not None else None,
            'status_counts': dict(status_counts),
            'transport_errors_sample': errors[:20],
        },
        'passed': passed,
        'errors': failures,
    }
    _write_reports(json_path=json_path, md_path=md_path, report=report)
    print(f'Non-functional report JSON: {json_path}')
    print(f'Non-functional report MD: {md_path}')
    print(f'Status: {"PASS" if passed else "FAIL"}')
    if failures:
        for failure in failures:
            print(f'  - ERROR: {failure}')

    if args.record_event:
        performed_by = args.performed_by.strip()
        if not performed_by:
            print('--performed-by is required with --record-event.')
            sys.exit(1)
        settings = get_settings()
        dsn = to_psycopg_dsn(settings.postgres_dsn)
        details = {
            'mode': args.mode,
            'report_json': str(json_path),
            'report_markdown': str(md_path),
            'summary': report['summary'],
            'thresholds': report['thresholds'],
            'errors': failures,
        }
        try:
            event_id = record_control_event(
                dsn=dsn,
                control_type=CONTROL_TYPE_BY_MODE[args.mode],
                status='pass' if passed else 'fail',
                control_scope=args.scope,
                performed_by=performed_by,
                evidence_uri=str(md_path),
                details=details,
            )
            print(f'Recorded control event: {event_id}')
        except psycopg.OperationalError as exc:
            print(
                'Database connection failed while recording non-functional validation event. '
                'Ensure Postgres is running and migrations are applied.\n'
                f'Details: {exc}'
            )
            sys.exit(1)

    if not passed:
        sys.exit(2)


if __name__ == '__main__':
    main()
