# Tingting ticket backend

The backend owns ticket validation, identifiers, idempotency and persistence.
Run it through the root `docker compose up --build` command. Database schema
changes are managed only by Alembic; startup never drops or recreates tables.

Ticket attachment bodies are stored in S3-compatible object storage (MinIO in
local Compose); PostgreSQL stores metadata only. See
`../docs/security-hardening.md` and `../ENGINEERING.md` for API, authorization and scanner contracts.
