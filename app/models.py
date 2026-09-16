from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Date,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class IngestionRun(Base):
    __tablename__ = "ingestion_runs"

    id: Mapped[int] = mapped_column(
        BigInteger,
        Identity(),
        primary_key=True,
    )

    filename: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class ConstituentRecord(Base):
    __tablename__ = "constituent_records"

    id: Mapped[int] = mapped_column(
        BigInteger,
        Identity(),
        primary_key=True,
    )

    ingestion_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("ingestion_runs.id"),
        nullable=False,
    )

    index_code: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )

    isin: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
    )

    ticker: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )

    name: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    weight: Mapped[Decimal] = mapped_column(
        Numeric(18, 8),
        nullable=False,
    )

    shares: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
    )

    effective_date: Mapped[date] = mapped_column(
        Date,
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint(
            "ingestion_id",
            "index_code",
            "isin",
            "effective_date",
            name="uq_constituent_per_ingestion",
        ),
        Index(
            "ix_constituent_business_version",
            "index_code",
            "isin",
            "effective_date",
            "ingestion_id",
        ),
        Index(
            "ix_constituent_effective_date",
            "effective_date",
        ),
    )


class DeletionEvent(Base):
    __tablename__ = "deletion_events"

    id: Mapped[int] = mapped_column(
        BigInteger,
        Identity(),
        primary_key=True,
    )

    constituent_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("constituent_records.id"),
        nullable=False,
        unique=True,
    )

    deleted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )