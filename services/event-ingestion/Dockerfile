FROM python:3.12-slim
WORKDIR /app

# Shared library first — changes least often, best layer caching.
COPY shared/ /app/shared/
RUN pip install --no-cache-dir -e /app/shared/

# Service deps, then service code.
COPY services/event-ingestion/requirements.txt /app/svc/requirements.txt
RUN pip install --no-cache-dir -r /app/svc/requirements.txt
COPY services/event-ingestion/app/ /app/svc/app/

WORKDIR /app/svc
EXPOSE 8001
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]
