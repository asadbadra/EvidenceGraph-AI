# Backend image: the FastAPI layer over the research pipeline.
# Model weights are NOT packaged: the container reaches Ollama on the host
# (http://host.docker.internal:11434/v1 via docker-compose.yml).
FROM python:3.12-slim

# Run as a non-root user; the app only needs its own directory + /tmp.
RUN useradd --create-home --uid 10001 appuser

WORKDIR /srv/evidencegraph

# Install dependencies first for layer caching.
COPY pyproject.toml README.md ./
COPY app ./app
COPY data/sample ./data/sample
RUN pip install --no-cache-dir .

# Pre-create the data dir with correct ownership for the mounted volume.
RUN mkdir -p /srv/evidencegraph/data && chown -R appuser:appuser /srv/evidencegraph
USER appuser

ENV DATABASE_URL=sqlite:////srv/evidencegraph/data/evidencegraph.db \
    PYTHONUNBUFFERED=1

EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4).status==200 else 1)"

CMD ["uvicorn", "app.api:app", "--host", "0.0.0.0", "--port", "8000"]
