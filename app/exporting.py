from datetime import date

from sqlalchemy import Select, func, select

from app.models import ConstituentRecord, DeletionEvent


def build_export_query(
    start_date: date,
    end_date: date,
) -> Select:
    ranked = (
        select(
            ConstituentRecord.id.label("id"),
            ConstituentRecord.ingestion_id.label("ingestion_id"),
            ConstituentRecord.index_code.label("index_code"),
            ConstituentRecord.isin.label("isin"),
            ConstituentRecord.ticker.label("ticker"),
            ConstituentRecord.name.label("name"),
            ConstituentRecord.weight.label("weight"),
            ConstituentRecord.shares.label("shares"),
            ConstituentRecord.effective_date.label("effective_date"),

            func.row_number()
            .over(
                partition_by=(
                    ConstituentRecord.index_code,
                    ConstituentRecord.isin,
                    ConstituentRecord.effective_date,
                ),
                order_by=ConstituentRecord.ingestion_id.desc(),
            )
            .label("version_rank"),
        )
        .where(
            ConstituentRecord.effective_date.between(
                start_date,
                end_date,
            )
        )
        .subquery()
    )

    statement = (
        select(
            ranked.c.id,
            ranked.c.ingestion_id,
            ranked.c.index_code,
            ranked.c.isin,
            ranked.c.ticker,
            ranked.c.name,
            ranked.c.weight,
            ranked.c.shares,
            ranked.c.effective_date,
        )
        .outerjoin(
            DeletionEvent,
            DeletionEvent.constituent_id == ranked.c.id,
        )
        .where(
            ranked.c.version_rank == 1,
            DeletionEvent.id.is_(None),
        )
        .order_by(
            ranked.c.effective_date,
            ranked.c.index_code,
            ranked.c.ticker,
            ranked.c.isin,
        )
    )

    return statement