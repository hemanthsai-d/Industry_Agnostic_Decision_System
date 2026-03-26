from __future__ import annotations

import subprocess
import sys


def main() -> None:
    subprocess.run(
        [sys.executable, "-m", "scripts.migrate", "migrate"],
        check=True,
    )
    subprocess.run(
        [sys.executable, "-m", "scripts.seed_db"],
        check=True,
    )
    print("Database initialized via migrations + seed.")


if __name__ == "__main__":
    main()
