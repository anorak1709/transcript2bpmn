"""Seed a demo workspace so the web app has something to explore without an LLM key.

    uv run python scripts/seed_demo.py [--api http://localhost:8000]

Creates an organization + API key (printed once) with the same sample the public demo's
sandboxes get (app/demo.py): two processes, two meetings each, a policy document and speaker
roles. Processing runs the real pipeline (normalize, validate, BPMN, merge, conflicts, policy
check) with the LLM replaced by the gold extraction for each file, so the maps are what a
perfect extraction would give, not a live model's output.
"""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.auth import create_key, create_org  # noqa: E402
from app.db.tenancy import system_session  # noqa: E402
from app.demo import build_sample  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", default="http://localhost:8000", help="only used to print the app's URL")
    ap.add_argument("--org", default="Demo workspace")
    args = ap.parse_args()

    with system_session() as db:
        org = create_org(db, args.org)
        key = create_key(db, org.id, "demo")
        db.commit()
        org_id = org.id
    build_sample(org_id)  # the same sample the public demo's sandboxes get (app/demo.py)
    print(f"organization: {org_id}\napi key (shown once): {key}\nopen: {args.api}/app/")


if __name__ == "__main__":
    main()
