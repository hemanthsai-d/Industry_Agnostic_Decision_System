from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys

PLACEHOLDERS = {
    'https://pager.example.invalid/webhook': 'ALERTMANAGER_PAGER_WEBHOOK_URL',
    'https://model-oncall.example.invalid/webhook': 'ALERTMANAGER_MODEL_ONCALL_WEBHOOK_URL',
    'https://platform-oncall.example.invalid/webhook': 'ALERTMANAGER_PLATFORM_ONCALL_WEBHOOK_URL',
    'https://ops-ticket.example.invalid/webhook': 'ALERTMANAGER_TICKET_WEBHOOK_URL',
}


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Render production Alertmanager config with real webhook endpoints.')
    parser.add_argument(
        '--template',
        default='observability/alertmanager/alertmanager.prod.example.yml',
        help='Path to template Alertmanager config.',
    )
    parser.add_argument(
        '--output',
        default='observability/alertmanager/alertmanager.prod.yml',
        help='Path to rendered production Alertmanager config.',
    )
    parser.add_argument(
        '--activate',
        action='store_true',
        help='Copy rendered production config to observability/alertmanager/alertmanager.yml',
    )
    parser.add_argument('--pager-url', default='', help='Critical pager webhook URL.')
    parser.add_argument('--model-oncall-url', default='', help='Model on-call warning webhook URL.')
    parser.add_argument('--platform-oncall-url', default='', help='Platform on-call warning webhook URL.')
    parser.add_argument('--ticket-url', default='', help='Ops ticket webhook URL.')
    return parser.parse_args()


def _resolve_value(cli_value: str, env_key: str) -> str:
    value = cli_value.strip()
    if value:
        return value
    return str(os.environ.get(env_key, '')).strip()


def _is_placeholder(value: str) -> bool:
    lowered = value.lower()
    return (
        'example.invalid' in lowered
        or '<' in lowered
        or 'changeme' in lowered
        or 'replace-me' in lowered
    )


def main() -> None:
    args = _parse_args()
    values = {
        'ALERTMANAGER_PAGER_WEBHOOK_URL': _resolve_value(args.pager_url, 'ALERTMANAGER_PAGER_WEBHOOK_URL'),
        'ALERTMANAGER_MODEL_ONCALL_WEBHOOK_URL': _resolve_value(
            args.model_oncall_url,
            'ALERTMANAGER_MODEL_ONCALL_WEBHOOK_URL',
        ),
        'ALERTMANAGER_PLATFORM_ONCALL_WEBHOOK_URL': _resolve_value(
            args.platform_oncall_url,
            'ALERTMANAGER_PLATFORM_ONCALL_WEBHOOK_URL',
        ),
        'ALERTMANAGER_TICKET_WEBHOOK_URL': _resolve_value(args.ticket_url, 'ALERTMANAGER_TICKET_WEBHOOK_URL'),
    }

    missing = [key for key, value in values.items() if not value]
    if missing:
        print('Missing required webhook URLs:')
        for key in missing:
            print(f'  - {key}')
        print('Set these env vars or pass explicit CLI args, then rerun.')
        sys.exit(1)

    placeholders = [key for key, value in values.items() if _is_placeholder(value)]
    if placeholders:
        print('Refusing to render production Alertmanager config with placeholder webhook URLs:')
        for key in placeholders:
            print(f'  - {key}')
        print('Provide real incident platform endpoints, then rerun.')
        sys.exit(1)

    template_path = Path(args.template)
    output_path = Path(args.output)
    if not template_path.exists():
        print(f'Template not found: {template_path}')
        sys.exit(1)

    rendered = template_path.read_text(encoding='utf-8')
    for placeholder, env_key in PLACEHOLDERS.items():
        rendered = rendered.replace(placeholder, values[env_key])

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(rendered, encoding='utf-8')
    print(f'Rendered production Alertmanager config: {output_path}')

    if args.activate:
        active_path = Path('observability/alertmanager/alertmanager.yml')
        active_path.write_text(rendered, encoding='utf-8')
        print(f'Activated production Alertmanager config: {active_path}')


if __name__ == '__main__':
    main()
