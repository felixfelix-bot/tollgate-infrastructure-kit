FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml /app/
COPY src/ /app/src/
COPY proto/ /app/proto/

RUN pip install --no-cache-dir -e .

RUN mkdir -p /var/lib/dm-issuer

ENV DM_ISSUER_DB_PATH=/var/lib/dm-issuer/dm-issuer.db
ENV PYTHONUNBUFFERED=1

EXPOSE 8095

CMD ["python", "-m", "tollgate_dm_issuer"]
