# demo_normalization

Standalone CLI program that submits a fixed set of login events through the NAAS pipeline
and verifies the normalization output.

## Prerequisites

A running NAAS stack. Start it with:

```
docker compose up -d
```

Wait until all services report healthy:

```
docker compose ps
```

## Install dependencies

```
pip install -r demo/requirements.txt
```

The program requires only `rich`, `httpx`, and `psycopg[binary]`. It does not require
`naas_shared` to be installed (that package is used only as an optional soft import if
already present in the environment).

## Run

```
python demo/demo_normalization.py
```

## Flags

| Flag | Default | Description |
|------|---------|-------------|
| `--keep` | off | Retain submitted events in the database after the run instead of deleting them. |
| `--pace SECONDS` | `1.5` | Delay in seconds between scenes. Set to `0` to disable delay. |
| `--step` | off | Wait for Enter between scenes. Overrides `--pace`. |
| `--timeout SECONDS` | `30` | Maximum seconds to wait for a normalization result to appear. |
| `--skip-verify` | off | Skip the verification step; do not check normalization output. |
| `--ingest-url URL` | `http://localhost:8001` | Base URL for the event ingestion service. |
| `--db-dsn DSN` | (assembled from env) | Full psycopg DSN for direct postgres reads. Overrides individual `POSTGRES_*` env vars. |

## Environment variables

The following environment variables configure service endpoints (overridden by the
corresponding flags):

- `INGEST_URL` — event ingestion service base URL (default: `http://localhost:8001`)
- `NORM_URL` — identity normalization service base URL (default: `http://localhost:8002`)
- `POSTGRES_HOST` — PostgreSQL host (default: `localhost`)
- `POSTGRES_PORT` — PostgreSQL port (default: `5432`)
- `POSTGRES_DB` — database name
- `POSTGRES_USER` — database user
- `POSTGRES_PASSWORD` — database password

## Note on database access

This program reads postgres directly because the query API for normalized events is
designed but not yet built. The `--db-dsn` flag or `POSTGRES_*` environment variables
provide the connection credentials.

When running from the host shell (not inside a container), note that:

- The stack's Postgres password is `naas_dev_password`, not the script's default `naas`.
- `POSTGRES_HOST=postgres` in `.env` is a docker-internal service alias that is not
  reachable from the host — use `localhost` instead.

A host run typically needs an explicit DSN:

```
python demo/demo_normalization.py --db-dsn "host=localhost port=5432 dbname=naas user=naas password=naas_dev_password"
```

Or export the individual variables before running:

```
export POSTGRES_PASSWORD=naas_dev_password
python demo/demo_normalization.py
```
