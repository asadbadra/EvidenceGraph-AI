# Frontend image: Streamlit talking to the backend service over Compose net.
FROM python:3.12-slim

RUN useradd --create-home --uid 10001 appuser

WORKDIR /srv/frontend

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py ui_logic.py ./
RUN chown -R appuser:appuser /srv/frontend
USER appuser

ENV STREAMLIT_BROWSER_GATHER_USAGE_STATS=false \
    PYTHONUNBUFFERED=1

EXPOSE 8501
HEALTHCHECK --interval=15s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8501/_stcore/health', timeout=4).status==200 else 1)"

CMD ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0", "--server.headless=true"]
