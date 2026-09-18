FROM mcr.microsoft.com/playwright/python:v1.63.0-noble

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    COMPETITOR_INTERVAL=20 \
    AMAZON_INTERVAL=45 \
    STORES_INTERVAL=120 \
    STATE_SYNC_INTERVAL=60

COPY telegram_deals_bot_v7_dev/requirements.txt /tmp/v7-requirements.txt
COPY amazon_dynamic_runtime_v8/telegram_deals_bot_v1_ready/requirements.txt /tmp/amz-requirements.txt
COPY amazon_dynamic_runtime_v8/requirements_ready.txt /tmp/runtime-requirements.txt

RUN pip install --no-cache-dir \
    -r /tmp/v7-requirements.txt \
    -r /tmp/amz-requirements.txt \
    -r /tmp/runtime-requirements.txt \
    playwright==1.63.0

COPY . /app

RUN mkdir -p /app/.runtime_state

CMD ["python3", "scripts/run_realtime_worker.py"]
