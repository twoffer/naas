FROM python:3.12-slim
WORKDIR /app

# System build deps for python-ldap (C extension that wraps the OpenLDAP client library).
# python:3.12-slim has no C compiler or LDAP headers — these must be installed before pip.
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    build-essential \
    libldap2-dev \
    libsasl2-dev \
    && rm -rf /var/lib/apt/lists/*

# Shared library first — changes least often, best layer caching.
COPY shared/ /app/shared/
RUN pip install --no-cache-dir -e /app/shared/

# Service deps, then service code.
COPY services/identity-normalization/requirements.txt /app/svc/requirements.txt
RUN pip install --no-cache-dir -r /app/svc/requirements.txt
COPY services/identity-normalization/app/ /app/svc/app/

# The service needs no root privileges at runtime; switch to a dedicated user.
RUN useradd --create-home --uid 10001 appuser && chown -R appuser:appuser /app/svc
USER appuser

WORKDIR /app/svc
EXPOSE 8002
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8002"]
