FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential curl \
    && rm -rf /var/lib/apt/lists/*

COPY apps/api/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY apps/api/app ./app
# /config may be shadowed by an empty volume mount (Coolify/local). Keep a
# second copy that volumes do not cover, and seed /config at container start.
COPY config /config
COPY config /opt/default-config
COPY apps/api/docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

EXPOSE 8008

ENTRYPOINT ["/entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8008"]
