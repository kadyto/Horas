# syntax=docker/dockerfile:1
FROM python:3.12-slim

ARG SOURCE_DIR=.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DATA_DIR=/data
WORKDIR /app

COPY ${SOURCE_DIR}/requirements.txt ./requirements.txt
# The optional CA is only used by managed build environments with an HTTPS proxy.
RUN --mount=type=secret,id=proxy_ca \
    if [ -f /run/secrets/proxy_ca ]; then \
      PIP_CERT=/run/secrets/proxy_ca pip install --no-cache-dir -r requirements.txt; \
    else \
      pip install --no-cache-dir -r requirements.txt; \
    fi

RUN groupadd --gid 10001 horas \
    && useradd --uid 10001 --gid horas --no-create-home horas \
    && mkdir -p /data \
    && chown horas:horas /data
COPY --chown=10001:10001 ${SOURCE_DIR}/app ./app
USER 10001:10001
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=3)"
# Preload initializes the shared key and schema once before forking workers.
CMD ["gunicorn", "--preload", "--bind=0.0.0.0:8000", "--workers=2", "--threads=2", "--timeout=60", "--access-logfile=-", "--error-logfile=-", "app:create_app()"]
