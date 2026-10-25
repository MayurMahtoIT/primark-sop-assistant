# Mesh API + PostgreSQL (pgvector) Setup

The project uses Mesh API for both `text-embedding-3-small` embeddings and `openai/gpt-oss-20b` generation. PostgreSQL with the `pgvector` extension stores the resulting 1536-dimensional vectors and SOP metadata.

1. Verify `.env` has your `MESH_API_KEY` set (from [Mesh API](https://app.meshapi.ai) -> API Keys).
2. Install `backend/requirements.txt` into your virtual environment:
   ```powershell
   python -m pip install -r backend/requirements.txt
   ```
3. Stop old containers (if any were running) and start PostgreSQL + API:
   ```powershell
   docker compose down
   docker compose up --build -d postgres api
   ```
4. Run SOP ingestion into PostgreSQL:
   ```powershell
   docker compose --profile ingest run --rm ingest
   ```
5. Smoke test Mesh API + PostgreSQL:
   ```powershell
   python scripts/verify_mesh.py
   python scripts/verify_postgres.py
   ```
6. Open the chatbot UI in your browser at `http://127.0.0.1:8080`.
   - Health check: `http://127.0.0.1:8080/healthz`
   - Readiness: `http://127.0.0.1:8080/readyz`
   - API Docs: `http://127.0.0.1:8080/docs`
