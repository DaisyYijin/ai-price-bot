FROM python:3.12-slim

ARG GIT_SHA=dev
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    APP_VERSION=${GIT_SHA}

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && playwright install --with-deps chromium \
    && playwright cache clean || true

COPY app ./app

RUN useradd --create-home runner \
    && mkdir -p /app/config /app/data /app/logs \
    && chown -R runner:runner /app
USER runner

EXPOSE 2048 2222

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request,sys; [urllib.request.urlopen(u, timeout=3) for u in ('http://127.0.0.1:2048/healthz','http://127.0.0.1:2222/healthz')]; sys.exit(0)"

CMD ["python", "-m", "app.serve"]
