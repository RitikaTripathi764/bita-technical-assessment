# BITA Index Constituents API

This project is my solution for the BITA Python + PostgreSQL technical assessment.

The service accepts index constituent data from a CSV file, stores every ingestion in PostgreSQL without overwriting previous data, supports logical deletion, and exports the current constituent data for a selected date range.

The main focus of my implementation was keeping the ingestion history intact while still providing a clear definition of what should be considered the current version of a constituent.

---

## Tech stack

I used:

- Python
- FastAPI
- PostgreSQL
- SQLAlchemy
- Psycopg
- Pydantic
- Pytest
- Docker Compose

I kept the project synchronous because the main work here is CSV processing and PostgreSQL access, and I preferred keeping the implementation small and easy to follow rather than introducing asynchronous database handling without a clear need.

---

## Project structure

```text
.
├── app/
│   ├── __init__.py
│   ├── config.py
│   ├── database.py
│   ├── deletion.py
│   ├── exporting.py
│   ├── ingestion.py
│   ├── main.py
│   ├── models.py
│   ├── routes.py
│   └── schemas.py
│
├── tests/
│   ├── conftest.py
│   └── test_api.py
│
├── .env.example
├── .gitignore
├── docker-compose.yml
├── pytest.ini
├── requirements.txt
└── README.md
```

---

## Running the project

### Requirements

You need:

- Python
- Docker Desktop

### 1. Create a virtual environment

On Windows PowerShell:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
```

If PowerShell blocks the activation script, the policy can be changed for the current terminal session only:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

### 2. Install dependencies

```powershell
pip install -r requirements.txt
```

### 3. Create the environment file

```powershell
Copy-Item .env.example .env
```

The example configuration uses local PostgreSQL databases running through Docker.

### 4. Start PostgreSQL

```powershell
docker compose up -d
```

Check that the containers are healthy:

```powershell
docker compose ps
```

The development database runs on port `5432`.

The test database runs separately on port `5433`.

### 5. Start the API

```powershell
uvicorn app.main:app --reload
```

Swagger documentation is available at:

```text
http://127.0.0.1:8000/docs
```

The health endpoint is:

```text
GET /health
```

---

# API endpoints

## Upload CSV

```text
POST /constituents/upload
```

The CSV is expected to contain:

```text
index_code
isin
ticker
name
weight
shares
effective_date
```

Example successful response:

```json
{
  "message": "CSV uploaded successfully",
  "ingestion_id": 1,
  "filename": "index_constituents_sample.csv",
  "rows_inserted": 54
}
```

Each upload creates a new ingestion.

Previously loaded constituent records are never updated or replaced.

---

## Delete a row

```text
DELETE /constituents/{record_id}
```

I use the internal database record ID for this endpoint.

A delete request does **not** remove the constituent row from PostgreSQL.

Instead, a separate deletion event is created.

This means the original ingested data stays available and unchanged.

Example:

```text
constituent_records

id = 120
MSFT
...
```

After deleting record `120`, that row still exists.

A new record is added to:

```text
deletion_events

constituent_id = 120
deleted_at = ...
```

The API then stops returning that constituent version.

Calling DELETE multiple times for the same record does not create multiple deletion events.

---

## Export data

```text
GET /constituents/export
```

Query parameters:

```text
start_date
end_date
format
```

`format` can be:

```text
json
csv
```

Example:

```text
GET /constituents/export?start_date=2026-01-01&end_date=2026-12-31&format=json
```

The date range is inclusive.

Deleted current records are not returned.

---

# How I handle ingestion history

The business key given in the assessment is:

```text
index_code + isin + effective_date
```

I did not make this combination globally unique in the database.

That was intentional.

For example, this is valid:

```text
Upload 1
BITA100 + ISIN-X + 2026-01-02

Upload 2
BITA100 + ISIN-X + 2026-01-02
```

Both versions should stay in the database because the task requires ingestion history to be preserved.

Each constituent therefore also has an internal database ID and an `ingestion_id`.

---

## How I define "current"

The assessment leaves the definition of the current record to the candidate.

My rule is:

> For a given business key, the record from the latest ingestion is considered current.

I resolve this in PostgreSQL using `ROW_NUMBER()` over:

```text
index_code
isin
effective_date
```

ordered by:

```text
ingestion_id DESC
```

The row with rank `1` is the current version.

Older versions remain stored but are not returned by the normal export endpoint.

---

# Deletion and an important edge case

One part I considered carefully was what should happen when the newest version is deleted.

For example:

```text
Upload 1
MSFT -> weight 18%

Upload 2
MSFT -> weight 20%
```

Upload 2 is the current version.

If the second version is deleted, I do **not** return the 18% version again.

I resolve the newest version first and apply deletion afterwards.

This was intentional because filtering deleted records first could make an older version suddenly become visible again, which I found misleading.

So after deleting the newest version:

```text
MSFT -> not returned
```

If a later upload introduces MSFT again:

```text
Upload 3
MSFT -> weight 21%
```

that new version becomes current and is returned normally.

---

# CSV processing

I considered using Pandas because it would make reading the sample file straightforward.

For this task, however, I only needed to read rows, validate them and insert them into PostgreSQL.

I therefore used Python's built-in `csv` module.

One reason for this decision was memory usage.

Instead of loading the whole file into memory, rows can be processed incrementally.

The rows are collected into batches before being inserted.

Conceptually:

```text
read rows 1-1000
        ↓
insert batch

read rows 1001-2000
        ↓
insert batch
```

This reduces database round trips while keeping memory usage relatively stable as the file grows.

I did not use PostgreSQL `COPY` or another native PostgreSQL bulk loading mechanism because the exercise explicitly excludes them.

---

# Transactions

Each CSV upload runs inside one database transaction.

The intended behavior is:

```text
BEGIN

create ingestion
insert all batches

everything succeeds
        ↓
COMMIT
```

If any row fails:

```text
ROLLBACK
```

This means an invalid row near the end of a file cannot leave a partially imported ingestion in the database.

The automated tests include a case where more than one full batch is processed before an invalid row is introduced, to make sure the earlier inserts are also rolled back.

---

# Validation

The upload currently validates:

- that the file is a CSV
- required CSV headers
- duplicated header names
- required values
- weight values
- share values
- effective dates
- duplicate business keys inside the same ingestion

I intentionally kept the business validation limited to rules supported by the exercise.

For example, I did not invent additional rules about allowed weight ranges or financial methodology because these were not part of the specification.

---

# Data types

For `weight` I use PostgreSQL `NUMERIC` and Python `Decimal`.

I preferred this over a floating-point type because constituent weights are decimal financial values and I did not want to introduce unnecessary floating-point representation differences.

`shares` uses `BIGINT`.

`effective_date` uses PostgreSQL `DATE`.

Upload and deletion times use timezone-aware timestamps.

---

# Database structure

The main tables are:

```text
ingestion_runs
        |
        | one-to-many
        v
constituent_records
        |
        | optional deletion
        v
deletion_events
```

### `ingestion_runs`

Stores information about each uploaded file.

### `constituent_records`

Stores all constituent versions.

Records are append-only between ingestions.

### `deletion_events`

Stores logical deletion information without modifying or physically deleting the original constituent record.

---

# Database indexes

I added indexes based on the main queries used by the service.

The most important one covers:

```text
index_code
isin
effective_date
ingestion_id
```

This supports looking up and ordering versions of the same business key.

I also index:

```text
effective_date
```

because exports are filtered by date range.

I avoided adding indexes to every column because indexes also have storage and insert costs.

---

# Export performance

CSV exports are returned as a streaming response.

Instead of first creating one large CSV string in memory, rows are written and returned progressively.

For JSON I kept the implementation simpler and materialize the result before returning it.

For this exercise I preferred that trade-off instead of adding more complicated streaming JSON handling.

For a production API with very large JSON result sets, I would probably add pagination or another form of bounded retrieval.

---

# Error handling

The API distinguishes between problems such as:

```text
400
invalid CSV content

404
requested constituent does not exist

422
invalid API/query input

500
unexpected database/server error
```

FastAPI also performs its own request validation for required fields and query parameters.

---

# Testing

The tests use a separate PostgreSQL database so they do not modify development data.

Run them with:

```powershell
pytest -v
```

The current suite contains 15 tests.

It covers:

- health check
- successful CSV upload
- repeated uploads
- append-only history
- latest-version selection
- logical deletion
- no resurrection of an older version
- new ingestion after deletion
- repeated DELETE behavior
- non-CSV files
- missing CSV columns
- invalid numeric values
- duplicate business keys inside one ingestion
- full transaction rollback
- JSON/CSV export and date validation

---

# Decisions and alternatives I considered

## Pandas vs built-in CSV reader

Pandas would make the sample file easy to read, but I did not need dataframe operations.

I chose the standard CSV reader because it also allows incremental processing.

---

## INSERT batches vs PostgreSQL COPY

For a large import I would normally consider benchmarking PostgreSQL `COPY`.

It is explicitly excluded by the task, so I used batched normal INSERT operations instead.

---

## Updating existing rows vs append-only versions

An update or upsert would make finding the current state simple, but it would remove or replace previous values.

That conflicts with the requirement to preserve ingestion history.

I therefore insert a new version on every load.

---

## `is_deleted` flag vs deletion events

A boolean flag would be simpler.

I chose a separate deletion table because it lets the originally ingested row stay unchanged and also records when the logical deletion happened.

---

## Async database access

FastAPI supports asynchronous endpoints, but my database operations and CSV processing are synchronous.

I did not add an asynchronous SQLAlchemy stack because it would increase complexity without giving a clear benefit for this exercise.

---

## Database migrations

For a production service I would normally use something like Alembic for schema migrations.

For this small standalone assessment I create the schema from SQLAlchemy metadata to keep setup straightforward.

---

# Things I would add for production

This implementation is intentionally limited to the scope of the exercise.

Depending on the production environment, I would consider adding:

- Alembic migrations
- authentication and authorization
- structured logging
- metrics and monitoring
- upload size limits
- stronger operational error reporting
- pagination for large JSON results
- background ingestion for very large files
- storage of original source files
- CI checks
- security and rate limiting

I left these out because I wanted the assessment solution to stay focused on the requested ingestion, history, deletion and export behavior.
