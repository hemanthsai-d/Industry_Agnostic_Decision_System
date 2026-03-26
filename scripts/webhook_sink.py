from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

app = FastAPI(title='Decision Platform Webhook Sink')
_LOCK = Lock()


def _events_path() -> Path:
    raw = os.environ.get('WEBHOOK_SINK_EVENTS_PATH', 'artifacts/reports/webhook_sink_events.jsonl').strip()
    path = Path(raw)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _append_event(event: dict[str, Any]) -> None:
    path = _events_path()
    with _LOCK:
        with path.open('a', encoding='utf-8') as handle:
            handle.write(json.dumps(event, separators=(',', ':')))
            handle.write('\n')


def _read_counts() -> tuple[dict[str, int], int]:
    path = _events_path()
    counts: dict[str, int] = {}
    total = 0
    if not path.exists():
        return counts, total
    with _LOCK:
        for line in path.read_text(encoding='utf-8').splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            route = str(event.get('route', ''))
            counts[route] = counts.get(route, 0) + 1
            total += 1
    return counts, total


async def _capture(route: str, request: Request) -> JSONResponse:
    raw = await request.body()
    payload: Any
    if raw:
        try:
            payload = json.loads(raw.decode('utf-8'))
        except (UnicodeDecodeError, json.JSONDecodeError):
            payload = {'raw_body': raw.decode('utf-8', errors='replace')}
    else:
        payload = {}

    event = {
        'ts_utc': datetime.now(timezone.utc).isoformat(),
        'route': route,
        'payload': payload,
        'content_type': request.headers.get('content-type', ''),
    }
    _append_event(event)
    return JSONResponse({'ok': True})


@app.get('/health')
async def health() -> JSONResponse:
    return JSONResponse({'status': 'ok'})


@app.get('/summary')
async def summary() -> JSONResponse:
    counts, total = _read_counts()
    return JSONResponse({'total': total, 'counts': counts, 'events_path': str(_events_path())})


@app.post('/reset')
async def reset() -> JSONResponse:
    path = _events_path()
    with _LOCK:
        path.write_text('', encoding='utf-8')
    return JSONResponse({'ok': True, 'events_path': str(path)})


@app.post('/pager')
async def pager(request: Request) -> JSONResponse:
    return await _capture('/pager', request)


@app.post('/model-oncall')
async def model_oncall(request: Request) -> JSONResponse:
    return await _capture('/model-oncall', request)


@app.post('/platform-oncall')
async def platform_oncall(request: Request) -> JSONResponse:
    return await _capture('/platform-oncall', request)


@app.post('/ticket')
async def ticket(request: Request) -> JSONResponse:
    return await _capture('/ticket', request)
