# syntax=docker/dockerfile:1.7
# ---- builder: resolve wheels into an isolated venv ----
FROM python:3.12-slim AS builder
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
WORKDIR /build
COPY requirements.txt .
RUN pip install -r requirements.txt

# ---- runtime: small, non-root, no build tooling ----
FROM python:3.12-slim AS runtime
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH"
RUN useradd --create-home --uid 10001 appuser
COPY --from=builder /opt/venv /opt/venv
WORKDIR /srv
COPY app ./app
# Use Mesh API for embeddings and generation; no model weights are bundled in this image.
USER 10001
RUN python -c "from openai import OpenAI; print('OpenAI-compatible Mesh API client ready')"
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=3s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=2).status==200 else 1)"
# The same image runs the API (default) and the ingestion job (command override: python -m app.ingestion ...)
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "2", "--proxy-headers", "--forwarded-allow-ips", "*", "--timeout-graceful-shutdown", "25"]
