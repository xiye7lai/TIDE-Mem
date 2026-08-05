from __future__ import annotations

import argparse
import asyncio

from tide_mem.config import Settings
from tide_mem.db import MemoryDB


async def purge(days: int) -> int:
    settings = Settings.from_env()
    settings.db_path.parent.mkdir(parents=True, exist_ok=True)
    db = MemoryDB(settings.db_path)
    await db.initialize()
    return await db.purge_older_than(days)


def main() -> int:
    parser = argparse.ArgumentParser(description="Delete TIDE-Mem evidence older than N days")
    parser.add_argument("--days", type=int, default=30)
    args = parser.parse_args()
    if args.days < 1:
        parser.error("--days must be at least 1")
    deleted = asyncio.run(purge(args.days))
    print(f"deleted_records={deleted}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
