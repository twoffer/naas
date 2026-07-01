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

The following environment variables configure service endpoints (`INGEST_URL` is
overridden by `--ingest-url`; the `POSTGRES_*` variables are overridden by `--db-dsn`;
`NORM_URL` has no corresponding flag):

- `INGEST_URL` — event ingestion service base URL (default: `http://localhost:8001`)
- `NORM_URL` — identity normalization service base URL (default: `http://localhost:8002`)
- `POSTGRES_HOST` — PostgreSQL host (default: `localhost`)
- `POSTGRES_PORT` — PostgreSQL port (default: `5432`)
- `POSTGRES_DB` — database name (default: `naas`)
- `POSTGRES_USER` — database user (default: `naas`)
- `POSTGRES_PASSWORD` — database password (**required** unless `--db-dsn` is supplied;
  the script exits with an error if neither is set)

## Scenes

The demo submits six fixed login events and verifies the normalization output of each. The numbers it renders are read back from PostgreSQL; the script asserts *relative* invariants (confidence orderings, which source won which attribute), never exact confidence values.

| # | User / protocol | What it demonstrates | Enrichment | Resolution |
|---|-----------------|----------------------|------------|------------|
| 1 | frank / OIDC | Clean single-source baseline (frank is not in the directory) | skipped (no match) | all `single_source` |
| 2 | frank / SAML | Same user, SAML-native attribute keys | skipped (no match) | all `single_source` |
| 3 | grace / LDAP | Native LDAP bind, DN-encoded group membership | **skipped** (LDAP events self-skip) | all `single_source` |
| 4 | mallory / SAML | Unmapped values penalized/discarded: department `Sorcery` retained with a −0.2 penalty; `employee_type "wizard"` → `null` | skipped (no match) | `single_source`, lower confidence |
| 5 | alice / OIDC | Token and directory **agree** → confidence climbs | applied (LDAP) | `unanimous` scalars, `list_merge` groups |
| 6 | diana / OIDC | **Finale:** sources **disagree**, so two different sources win two attributes — `display_name` → **oidc** (`Di Prince`), `department` → **ldap** (`Engineering`); `vpn-users` is back-populated from the directory | applied (LDAP) | `priority` splits + corroborated `list_merge` |

The confidence orderings the script enforces: `C(4) < C(2) < C(1) < C(3)`, `C(5) > C(1)`, and `C(6) < C(5)`.

## Troubleshooting

- **`POSTGRES_PASSWORD is not set`** — export it (dev default `naas_dev_password`) or pass a full `--db-dsn`.
- **Can't connect to Postgres on a host run** — `.env` sets `POSTGRES_HOST=postgres`, a docker-internal alias not reachable from the host. From the host use `localhost` (the script's default) or a full `--db-dsn`. See the database-access note below.
- **Preflight fails (`could not reach …`)** — the stack isn't healthy yet. Run `docker compose ps` and wait for every service to report `(healthy)` before retrying.
- **`Verification failed … Aborting render`** — the pipeline didn't produce the expected narrative, usually from config drift in `config/normalization.yaml` or a stale postgres volume. The per-problem messages name the expected vs. actual result; reset the volume with `docker compose down -v && docker compose up -d --build` if the config is unchanged.

## Note on database access

This program reads postgres directly because the query API for normalized events is
designed but not yet built. The `--db-dsn` flag or `POSTGRES_*` environment variables
provide the connection credentials.

When running from the host shell (not inside a container), note that:

- The stack's default Postgres password is `naas_dev_password` (see `.env.example`);
  the script has no password default and exits if `POSTGRES_PASSWORD` is unset.
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
