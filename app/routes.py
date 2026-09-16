import csv
from datetime import date
from io import StringIO
from typing import Literal

from fastapi import (APIRouter, Depends, File, HTTPException, Query, UploadFile, status)
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.database import get_db
from app.ingestion import CSVValidationError, ingest_csv
from app.schemas import (ConstituentExportItem, DeleteResponse, UploadResponse)
from app.deletion import ConstituentNotFoundError, delete_constituent
from app.exporting import build_export_query

router = APIRouter(
    prefix="/constituents",
    tags=["constituents"],
)

def _csv_stream(rows):
    buffer = StringIO()
    writer = csv.writer(buffer)

    try:
        writer.writerow(["id", "ingestion_id", "index_code", "isin", "ticker", "name", "weight", "shares", "effective_date"])
        yield buffer.getvalue()
        buffer.seek(0)
        buffer.truncate(0)

        for row in rows:
            writer.writerow([row.id, row.ingestion_id, row.index_code, row.isin, row.ticker, row.name, row.weight, row.shares, row.effective_date.isoformat()])
            yield buffer.getvalue()
            buffer.seek(0)
            buffer.truncate(0)
    finally:
        rows.close()

@router.post(
    "/upload",
    response_model=UploadResponse,
    status_code=status.HTTP_201_CREATED,
)
def upload_constituents(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> UploadResponse:
    try:
        ingestion_id, rows_inserted = ingest_csv(db=db, file=file)
    except CSVValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="The uploaded file is not valid UTF-8 CSV.") from exc
    except csv.Error as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="The uploaded CSV is malformed.") from exc
    except IntegrityError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="The CSV contains duplicate business keys within the same ingestion.") from exc
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="A database error occurred during ingestion.") from exc

    return UploadResponse(
        message="CSV uploaded successfully",
        ingestion_id=ingestion_id,
        filename=file.filename or "",
        rows_inserted=rows_inserted,
    )

@router.delete(
    "/{record_id}",
    response_model=DeleteResponse,
)
def remove_constituent(
    record_id: int,
    db: Session = Depends(get_db),
) -> DeleteResponse:
    try:
        deleted_at = delete_constituent(db=db, record_id=record_id)
    except ConstituentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="A database error occurred while deleting the record.") from exc

    return DeleteResponse(
        message="Constituent deleted from API visibility",
        record_id=record_id,
        deleted_at=deleted_at,
    )

@router.get("/export")
def export_constituents(
    start_date: date = Query(...),
    end_date: date = Query(...),
    response_format: Literal["json", "csv"] = Query("json", alias="format"),
    db: Session = Depends(get_db),
):
    if start_date > end_date:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="start_date must be before or equal to end_date.",
        )

    statement = build_export_query(start_date=start_date, end_date=end_date)

    if response_format == "csv":
        try:
            result = db.execute(statement.execution_options(yield_per=1000))
        except SQLAlchemyError as exc:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="A database error occurred while exporting data.") from exc

        return StreamingResponse(
            _csv_stream(result),
            media_type="text/csv",
            headers={"Content-Disposition": 'attachment; filename="constituents_export.csv"'},
        )

    try:
        rows = db.execute(statement).all()
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="A database error occurred while exporting data.") from exc

    items = [
        ConstituentExportItem(
            id=row.id, ingestion_id=row.ingestion_id, index_code=row.index_code,
            isin=row.isin, ticker=row.ticker, name=row.name, weight=row.weight,
            shares=row.shares, effective_date=row.effective_date,
        )
        for row in rows
    ]

    return JSONResponse(content=[item.model_dump(mode="json") for item in items])