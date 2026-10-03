FROM python:3.11-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*
COPY vendors/requirements.txt vendors/requirements.txt
RUN pip install --no-cache-dir -r vendors/requirements.txt
COPY shared shared
COPY vendors vendors
CMD ["uvicorn", "vendors.main:app", "--host", "0.0.0.0", "--port", "8080"]
