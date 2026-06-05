from __future__ import annotations

import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db import ensure_local_dir, mark_migrated, mark_seeded


def main(argv: list[str]) -> int:
    command = argv[1] if len(argv) > 1 else "help"
    if command == "db-up":
        path = ensure_local_dir()
        print(f"Local fixture database directory ready: {path}")
        return 0
    if command == "migrate":
        path = mark_migrated()
        print(f"Migration marker written: {path}")
        return 0
    if command == "seed-fixtures":
        path = mark_seeded()
        print(f"Fixture seed marker written: {path}")
        return 0
    print("Usage: python3 apps/api/app/cli.py [db-up|migrate|seed-fixtures]")
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

