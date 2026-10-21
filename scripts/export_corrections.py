"""Turn consented corrections into evaluation cases (operator tool).

    uv run python scripts/export_corrections.py [--out eval/corrections/local]

Only workspaces that opted in (Settings → Help improve the drafts) are exported, at the level
they chose: anonymised cases carry what was changed but no meeting text; full cases carry the
meetings too, so `python -m eval.corrections_eval` can re-run them. The output folder is
git-ignored: it is customer data.
"""

import argparse
import json
import sys
from pathlib import Path

from sqlalchemy import select

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.corrections import export_cases  # noqa: E402
from app.db.models import Organization  # noqa: E402
from app.db.tenancy import system_session, tenant_session  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=ROOT / "eval/corrections/local")
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    with system_session() as db:
        orgs = [
            (o.id, o.share_corrections)
            for o in db.scalars(select(Organization).where(Organization.share_corrections != "off"))
        ]
    written = 0
    for org_id, level in orgs:
        with tenant_session(org_id) as db:
            for case in export_cases(db, db.get_one(Organization, org_id)):
                path = args.out / f"{org_id[:8]}-{case['case']}.json"
                path.write_text(json.dumps({"sharing": level, **case}, indent=2))
                written += 1
    print(f"{written} case(s) from {len(orgs)} consenting workspace(s) → {args.out}")


if __name__ == "__main__":
    main()
