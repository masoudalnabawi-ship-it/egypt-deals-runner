FROM mcr.microsoft.com/playwright/python:v1.63.0-noble

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    V14_DB_PATH=/app/.runtime_state/v14.db

COPY requirements-v14.txt /tmp/requirements-v14.txt

RUN pip install --no-cache-dir \
    -r /tmp/requirements-v14.txt

COPY deals_v14 /app/deals_v14
COPY scripts/run_v14.py /app/scripts/run_v14.py

RUN mkdir -p /app/.runtime_state

CMD ["python3", "scripts/run_v14.py"]
