from io import StringIO
from sqlalchemy import func, select
from app.models import ConstituentRecord, DeletionEvent, IngestionRun

VALID_CSV = """index_code,isin,ticker,name,weight,shares,effective_date
BITA100,US0000000001,AAA,Company A,60.5,1000,2026-01-02
BITA100,US0000000002,BBB,Company B,39.5,2000,2026-01-02
"""

def upload_csv(client, content=VALID_CSV, filename="constituents.csv"):
    return client.post(
        "/constituents/upload",
        files={"file": (filename, content, "text/csv")},
    )

def test_health_check(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "connected"}

def test_upload_csv_successfully(client):
    response = upload_csv(client)
    assert response.status_code == 201
    body = response.json()
    assert body["message"] == "CSV uploaded successfully"
    assert body["rows_inserted"] == 2
    assert body["filename"] == "constituents.csv"
    assert body["ingestion_id"] == 1

def test_repeated_upload_preserves_history(client, db_session):
    first = upload_csv(client)
    second = upload_csv(client)
    assert first.status_code == 201
    assert second.status_code == 201

    ingestion_count = db_session.scalar(select(func.count()).select_from(IngestionRun))
    constituent_count = db_session.scalar(select(func.count()).select_from(ConstituentRecord))

    assert ingestion_count == 2
    assert constituent_count == 4

def test_export_returns_only_latest_versions(client):
    upload_csv(client)
    upload_csv(client)
    response = client.get("/constituents/export", params={"start_date": "2026-01-01", "end_date": "2026-12-31", "format": "json"})
    assert response.status_code == 200
    rows = response.json()
    assert len(rows) == 2
    assert all(row["ingestion_id"] == 2 for row in rows)

def test_deleted_current_record_is_not_exported(client):
    upload_csv(client)
    upload_csv(client)
    export_response = client.get("/constituents/export", params={"start_date": "2026-01-01", "end_date": "2026-12-31", "format": "json"})
    rows = export_response.json()
    record_to_delete = rows[0]
    
    response = client.delete(f"/constituents/{record_to_delete['id']}")
    assert response.status_code == 200
    
    second_export = client.get("/constituents/export", params={"start_date": "2026-01-01", "end_date": "2026-12-31", "format": "json"})
    remaining = second_export.json()
    assert len(remaining) == 1
    assert all(row["id"] != record_to_delete["id"] for row in remaining)

def test_delete_does_not_resurrect_older_version(client):
    upload_csv(client)
    upload_csv(client)
    current = client.get("/constituents/export", params={"start_date": "2026-01-01", "end_date": "2026-12-31", "format": "json"}).json()
    deleted_record = current[0]
    
    client.delete(f"/constituents/{deleted_record['id']}")
    
    after_delete = client.get("/constituents/export", params={"start_date": "2026-01-01", "end_date": "2026-12-31", "format": "json"}).json()
    same_business_key = [row for row in after_delete if (row["index_code"] == deleted_record["index_code"] and row["isin"] == deleted_record["isin"] and row["effective_date"] == deleted_record["effective_date"])]
    assert same_business_key == []

def test_new_upload_after_delete_becomes_visible(client):
    upload_csv(client)
    upload_csv(client)
    current = client.get("/constituents/export", params={"start_date": "2026-01-01", "end_date": "2026-12-31", "format": "json"}).json()
    
    client.delete(f"/constituents/{current[0]['id']}")
    
    before_new_upload = client.get("/constituents/export", params={"start_date": "2026-01-01", "end_date": "2026-12-31", "format": "json"}).json()
    assert len(before_new_upload) == 1
    
    third_upload = upload_csv(client)
    assert third_upload.status_code == 201
    
    after_new_upload = client.get("/constituents/export", params={"start_date": "2026-01-01", "end_date": "2026-12-31", "format": "json"}).json()
    assert len(after_new_upload) == 2
    assert all(row["ingestion_id"] == 3 for row in after_new_upload)

def test_reject_non_csv_file(client):
    response = client.post("/constituents/upload", files={"file": ("document.txt", "hello", "text/plain")})
    assert response.status_code == 400

def test_reject_csv_with_missing_column(client):
    invalid_csv = "index_code,isin,ticker,name,weight,shares\nBITA100,US0000000001,AAA,Company A,50,1000\n"
    response = upload_csv(client, content=invalid_csv)
    assert response.status_code == 400
    assert "missing columns" in response.json()["detail"]

def test_reject_invalid_weight(client):
    invalid_csv = "index_code,isin,ticker,name,weight,shares,effective_date\nBITA100,US0000000001,AAA,Company A,banana,1000,2026-01-02\n"
    response = upload_csv(client, content=invalid_csv)
    assert response.status_code == 400
    assert "invalid weight" in response.json()["detail"]

def test_failed_ingestion_rolls_back_everything(client, db_session):
    lines = ["index_code,isin,ticker,name,weight,shares,effective_date"]
    for i in range(1001):
        lines.append(f"BITA100,US{i:010d},T{i},Company {i},1.0,1000,2026-01-02")
    lines.append("BITA100,US9999999999,BAD,Bad Company,not-a-number,1000,2026-01-02")
    
    large_invalid_csv = "\n".join(lines)
    response = upload_csv(client, content=large_invalid_csv)
    
    assert response.status_code == 400
    ingestion_count = db_session.scalar(select(func.count()).select_from(IngestionRun))
    constituent_count = db_session.scalar(select(func.count()).select_from(ConstituentRecord))
    
    assert ingestion_count == 0
    assert constituent_count == 0

def test_invalid_date_range_returns_422(client):
    response = client.get("/constituents/export", params={"start_date": "2026-12-31", "end_date": "2026-01-01", "format": "json"})
    assert response.status_code == 422

def test_csv_export(client):
    upload_csv(client)
    response = client.get("/constituents/export", params={"start_date": "2026-01-01", "end_date": "2026-12-31", "format": "csv"})
    assert response.status_code == 200
    assert "text/csv" in response.headers["content-type"]
    assert "index_code" in response.text
    assert "BITA100" in response.text


def test_duplicate_business_key_in_same_ingestion_rolls_back(client, db_session):
    duplicate_csv = """index_code,isin,ticker,name,weight,shares,effective_date
BITA100,US0000000001,AAA,Company A,60,1000,2026-01-02
BITA100,US0000000001,AAA,Company A,61,1000,2026-01-02
"""
    response = upload_csv(client, content=duplicate_csv)
    assert response.status_code == 400

    ingestion_count = db_session.scalar(select(func.count()).select_from(IngestionRun))
    constituent_count = db_session.scalar(select(func.count()).select_from(ConstituentRecord))
    
    assert ingestion_count == 0
    assert constituent_count == 0

def test_repeated_delete_is_idempotent(client, db_session):
    upload_csv(client)
    records = client.get(
        "/constituents/export",
        params={"start_date": "2026-01-01", "end_date": "2026-12-31", "format": "json"},
    ).json()
    
    record_id = records[0]["id"]
    first = client.delete(f"/constituents/{record_id}")
    second = client.delete(f"/constituents/{record_id}")
    
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["deleted_at"] == second.json()["deleted_at"]

    deletion_count = db_session.scalar(select(func.count()).select_from(DeletionEvent))
    assert deletion_count == 1    