"""Object-storage half of backups (the database half is pg_dump; see scripts/backup.sh).

    python -m app.backup dump <dir>       # every object in S3_BUCKET -> <dir>/<key>
    python -m app.backup restore <dir>    # <dir>/<key> -> S3_BUCKET (bucket created if needed)

Managed deployments (RDS, S3) should prefer provider snapshots and bucket versioning; this
covers self-hosted MinIO and gives a portable copy.
"""

import argparse
import sys
from pathlib import Path

from app import storage


def dump(target: Path) -> int:
    n = 0
    for key in storage.list_keys(""):
        dest = target / key
        if not dest.resolve().is_relative_to(target.resolve()):
            raise ValueError(f"refusing unsafe object key {key!r}")
        dest.parent.mkdir(parents=True, exist_ok=True)
        storage.download(key, dest)
        n += 1
    return n


def restore(source: Path) -> int:
    n = 0
    for path in sorted(p for p in source.rglob("*") if p.is_file()):
        storage.put_file(path.relative_to(source).as_posix(), path)
        n += 1
    return n


def main() -> None:
    ap = argparse.ArgumentParser(prog="python -m app.backup")
    ap.add_argument("action", choices=["dump", "restore"])
    ap.add_argument("dir", type=Path)
    args = ap.parse_args()
    n = dump(args.dir) if args.action == "dump" else restore(args.dir)
    print(f"{args.action}: {n} objects", file=sys.stderr)


if __name__ == "__main__":
    main()
