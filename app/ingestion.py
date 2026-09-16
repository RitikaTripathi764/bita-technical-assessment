import csv
from collections import Counter
from datetime import date
from decimal import Decimal, InvalidOperation
from io import TextIOWrapper
from fastapi import UploadFile
from sqlalchemy import insert
from sqlalchemy.orm import Session
from app.models import ConstituentRecord, IngestionRun

BATCH_SIZE = 1000

REQUIRED_COLUMNS = {
    "index_code",
    "isin",
    "ticker",
    "name",
    "weight",
    "shares",
    "effective_date",
}

class CSVValidationError(ValueError):
    pass

def _required_text(row: dict, column: str, row_number: int) -> str:
    value = row.get(column)
    if not value or not str(value).strip():
        raise CSVValidationError(f"Row {row_number}: missing value for '{column}'.")
    return str(value).strip()

def _parse_row(row: dict[str, str | None], row_number: int, ingestion_id: int) -> dict:
    if None in row:
        raise CSVValidationError(f"Row {row_number}: too many values were provided.")

    index_code = _required_text(row, "index_code", row_number)
    isin = _required_text(row, "isin", row_number)
    ticker = _required_text(row, "ticker", row_number)
    name = _required_text(row, "name", row_number)

    weight_raw = _required_text(row, "weight", row_number)
    shares_raw = _required_text(row, "shares", row_number)
    effective_date_raw = _required_text(row, "effective_date", row_number)

    try:
        weight = Decimal(weight_raw)
    except InvalidOperation as exc:
        raise CSVValidationError(f"Row {row_number}: invalid weight '{weight_raw}'.") from exc

    if not weight.is_finite():
        raise CSVValidationError(f"Row {row_number}: weight must be a finite number.")

    try:
        shares = int(shares_raw)
    except ValueError as exc:
        raise CSVValidationError(f"Row {row_number}: invalid shares value '{shares_raw}'.") from exc

    try:
        effective_date = date.fromisoformat(effective_date_raw)
    except ValueError as exc:
        raise CSVValidationError(f"Row {row_number}: invalid effective_date '{effective_date_raw}'. Expected YYYY-MM-DD.") from exc

    return {
        "ingestion_id": ingestion_id,
        "index_code": index_code,
        "isin": isin,
        "ticker": ticker,
        "name": name,
        "weight": weight,
        "shares": shares,
        "effective_date": effective_date,
    }

def ingest_csv(db: Session, file: UploadFile) -> tuple[int, int]:
    filename = file.filename or ""

    if not filename.lower().endswith(".csv"):
        raise CSVValidationError("Only CSV files are supported.")

    file.file.seek(0)
    text_stream = TextIOWrapper(file.file, encoding="utf-8-sig", newline="")

    try:
        reader = csv.DictReader(text_stream)

        if reader.fieldnames is None:
            raise CSVValidationError("The CSV file does not contain a header row.")

        fieldnames = [field.strip() if field else "" for field in reader.fieldnames]

        column_counts = Counter(fieldnames)
        duplicate_columns = sorted(column for column, count in column_counts.items() if count > 1)

        if duplicate_columns:
            raise CSVValidationError("Duplicate CSV columns: " + ", ".join(duplicate_columns))

        reader.fieldnames = fieldnames
        actual_columns = set(fieldnames)

        if actual_columns != REQUIRED_COLUMNS:
            missing = sorted(REQUIRED_COLUMNS - actual_columns)
            unexpected = sorted(actual_columns - REQUIRED_COLUMNS)
            problems = []
            if missing:
                problems.append(f"missing columns: {', '.join(missing)}")
            if unexpected:
                problems.append(f"unexpected columns: {', '.join(unexpected)}")
            raise CSVValidationError("Invalid CSV columns: " + "; ".join(problems))

        with db.begin():
            ingestion = IngestionRun(filename=filename)
            db.add(ingestion)
            db.flush()
            ingestion_id = ingestion.id

            batch: list[dict] = []
            rows_inserted = 0

            for row_number, row in enumerate(reader, start=2):
                parsed_row = _parse_row(row=row, row_number=row_number, ingestion_id=ingestion_id)
                batch.append(parsed_row)

                if len(batch) >= BATCH_SIZE:
                    db.execute(insert(ConstituentRecord), batch)
                    rows_inserted += len(batch)
                    batch.clear()

            if batch:
                db.execute(insert(ConstituentRecord), batch)
                rows_inserted += len(batch)

            if rows_inserted == 0:
                raise CSVValidationError("The CSV file contains no data rows.")

        return ingestion_id, rows_inserted

    finally:
        text_stream.detach()