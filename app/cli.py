"""Admin CLI (no signup/SSO yet: organizations and keys are issued by an operator).

python -m app.cli create-org "Acme Corp"          # prints org id + its first API key
python -m app.cli create-key <org_id> --name ci   # another key for an org
python -m app.cli revoke-key <prefix>
python -m app.cli set-quota <org_id> 500         # transcripts per month; no number = unlimited
"""

import argparse
from datetime import UTC, datetime

from sqlalchemy import select

from app.auth import create_key, create_org
from app.db.models import ApiKey, Organization
from app.db.tenancy import system_session


def main() -> None:
    ap = argparse.ArgumentParser(prog="python -m app.cli")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("create-org")
    p.add_argument("name")
    p = sub.add_parser("create-key")
    p.add_argument("org_id")
    p.add_argument("--name", default="default")
    p = sub.add_parser("revoke-key")
    p.add_argument("prefix")
    p = sub.add_parser("set-quota", help="monthly transcripts an org may process; omit n for unlimited")
    p.add_argument("org_id")
    p.add_argument("n", type=int, nargs="?")
    args = ap.parse_args()

    with system_session() as db:
        if args.cmd == "create-org":
            org = create_org(db, args.name)
            key = create_key(db, org.id)
            print(f"organization: {org.id}\napi key (shown once): {key}")
        elif args.cmd == "create-key":
            print(f"api key (shown once): {create_key(db, args.org_id, args.name)}")
        elif args.cmd == "set-quota":
            db.get_one(Organization, args.org_id).monthly_jobs_quota = args.n
            print(f"quota for {args.org_id}: {args.n if args.n is not None else 'unlimited'}")
        else:
            row = db.scalars(select(ApiKey).where(ApiKey.prefix == args.prefix)).one()
            row.revoked_at = datetime.now(UTC)
            print(f"revoked {row.prefix}")
        db.commit()


if __name__ == "__main__":
    main()
