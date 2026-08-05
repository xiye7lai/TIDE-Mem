FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    TIDE_DB_PATH=/data/tide_mem.sqlite3

WORKDIR /app

LABEL org.opencontainers.image.title="TIDE-Mem" \
      org.opencontainers.image.version="0.1.0-amc2026" \
      org.opencontainers.image.description="Temporal, identity-isolated, dual-view evidence memory"

COPY requirements.txt ./
RUN apt-get update \
    && apt-get install -y --no-install-recommends gosu \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir -r requirements.txt \
    && useradd --create-home --uid 10001 tide \
    && mkdir -p /data \
    && chown -R tide:tide /app /data

COPY --chown=tide:tide tide_mem ./tide_mem
COPY --chown=tide:tide scripts ./scripts
COPY deploy/docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
COPY --chown=tide:tide pyproject.toml README.md LICENSE ./

RUN chmod 0755 /usr/local/bin/docker-entrypoint.sh

VOLUME ["/data"]
EXPOSE 8000

HEALTHCHECK --interval=20s --timeout=5s --start-period=20s --retries=5 \
  CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:' + os.getenv('PORT', '8000') + '/health', timeout=4).read()" || exit 1

ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["sh", "-c", "exec uvicorn tide_mem.api:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1 --backlog 2048 --timeout-keep-alive 75"]
