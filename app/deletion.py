from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ConstituentRecord, DeletionEvent


class ConstituentNotFoundError(ValueError):
    pass


def delete_constituent(
    db: Session,
    record_id: int,
) -> datetime:
    record = db.get(ConstituentRecord, record_id)

    if record is None:
        raise ConstituentNotFoundError(
            f"Constituent record {record_id} does not exist."
        )

    existing_deletion = db.scalar(
        select(DeletionEvent).where(
            DeletionEvent.constituent_id == record_id
        )
    )

    if existing_deletion is not None:
        return existing_deletion.deleted_at

    deleted_at = datetime.now(timezone.utc)

    deletion = DeletionEvent(
        constituent_id=record_id,
        deleted_at=deleted_at,
    )

    db.add(deletion)
    db.commit()

    return deleted_at