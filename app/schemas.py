from datetime import date, datetime
from decimal import Decimal
from pydantic import BaseModel

class UploadResponse(BaseModel):
    message: str
    ingestion_id: int
    filename: str
    rows_inserted: int

class DeleteResponse(BaseModel):
    message: str
    record_id: int
    deleted_at: datetime

class ConstituentExportItem(BaseModel):
    id: int
    ingestion_id: int
    index_code: str
    isin: str
    ticker: str
    name: str
    weight: Decimal
    shares: int
    effective_date: date