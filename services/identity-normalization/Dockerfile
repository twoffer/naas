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

# Pinned dependency closure first — the compiled lockfile (service deps +
# shared's full transitive closure). This is the heavy, slowest-changing layer.
# python-ldap (above C deps) builds from sdist during this install.
COPY services/identity-normalization/requirements.txt /app/svc/requirements.txt
RUN pip install --no-cache-dir -r /app/svc/requirements.txt

# Shared library installed editable WITHOUT deps — its third-party dependencies
# are already pinned and installed by the lockfile above, so --no-deps keeps the
# locked versions authoritative and prevents any re-resolution.
COPY shared/ /app/shared/
RUN pip install --no-cache-dir -e /app/shared/ --no-deps

# Service code last — changes most often.
COPY services/identity-normalization/app/ /app/svc/app/

# The service needs no root privileges at runtime; switch to a dedicated user.
RUN useradd --create-home --uid 10001 appuser && chown -R appuser:appuser /app/svc
USER appuser

WORKDIR /app/svc
EXPOSE 8002
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8002"]
