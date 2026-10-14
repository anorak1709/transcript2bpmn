from typing import Any

from sqlalchemy.orm import Session

from app.db.models import AuditLog


def audit(db: Session, action: str, target_type: str, target_id: str, **details: Any) -> None:
    """Record an action in the caller's transaction (committed with the change it describes).
    `details` must be metadata only: ids, counts, names of things, never meeting content."""
    db.add(
        AuditLog(
            api_key_id=db.info.get("api_key_id"),
            action=action,
            target_type=target_type,
            target_id=target_id,
            details=details,
        )
    )
