from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path


def _iter_python_files(paths: list[str]) -> list[Path]:
    files: list[Path] = []
    for raw in paths:
        root = Path(raw)
        if not root.exists():
            continue
        if root.is_file() and root.suffix == '.py':
            files.append(root)
            continue
        for file_path in root.rglob('*.py'):
            if '__pycache__' in file_path.parts:
                continue
            files.append(file_path)
    return sorted(set(files))


def main() -> None:
    parser = argparse.ArgumentParser(description='Parse Python files to catch syntax errors early.')
    parser.add_argument(
        'paths',
        nargs='*',
        default=['app', 'model_server', 'mcp_server', 'scripts', 'tests'],
    )
    args = parser.parse_args()

    files = _iter_python_files(args.paths)
    if not files:
        print('No Python files found for static check.')
        return

    errors: list[str] = []
    for file_path in files:
        try:
            source = file_path.read_text(encoding='utf-8')
            ast.parse(source, filename=str(file_path))
        except SyntaxError as exc:
            errors.append(f'{file_path}:{exc.lineno}:{exc.offset} {exc.msg}')

    if errors:
        print('Static check failed:')
        for err in errors:
            print(f'  - {err}')
        sys.exit(1)

    print(f'Static check passed for {len(files)} files.')


if __name__ == '__main__':
    main()
