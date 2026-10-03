# Build context is the repo root (sim-harness/) so we can include shared/.
FROM python:3.11-slim

WORKDIR /app

# curl is used by the compose healthcheck.
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY mailbox/requirements.txt ./mailbox/requirements.txt
RUN pip install --no-cache-dir -r mailbox/requirements.txt

COPY shared ./shared
COPY mailbox ./mailbox

EXPOSE 8080
CMD ["uvicorn", "mailbox.main:app", "--host", "0.0.0.0", "--port", "8080"]
