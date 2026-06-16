# Dependencies

> **How this repo pins and regenerates its Python dependencies.** Read this before
> adding, removing, or upgrading a package — it affects the dev venv, CI, and every
> service image. This is the operational how-to; the decision and trade-offs are in
> [ADR-0012](docs/adr/0012-dependency-pinning-reproducible-builds.md).

Python dependencies are pinned via compiled lockfiles so the same source resolves
to the same installed set in every environment — the dev venv, CI, and each
service image.

## Layout: floors vs. locks

- **Floors** — the human-authored minimum versions — live in the `*.in` files and
  in `shared/pyproject.toml` (the shared package's runtime dependencies). These
  are the compile *inputs*; edit these to add, remove, or re-floor a dependency.
- **Locks** — the fully-pinned transitive closure — are the generated `*.txt`
  files. These are the install *artifacts*; never hand-edit them. Every
  environment installs from a lock:

  | Lockfile | Compiled from | Installed by |
  |----------|---------------|--------------|
  | `requirements-dev.txt` | `requirements-dev.in` + `shared/pyproject.toml` | CI unit + integration jobs |
  | `services/event-ingestion/requirements.txt` | that service's `requirements.in` + `shared/pyproject.toml` | `services/event-ingestion/Dockerfile` |
  | `services/identity-normalization/requirements.txt` | that service's `requirements.in` + `shared/pyproject.toml` | `services/identity-normalization/Dockerfile` |
  | `demo/requirements.txt` | `demo/requirements.in` | `demo/README.md` |

Each service lock is compiled with `shared/pyproject.toml` as a second input so
it pins **shared's entire transitive closure**, not just the service's own two or
three lines. The service images therefore install the lock first, then the shared
package editable with `pip install -e shared/ --no-deps` — the lock already pins
shared's dependencies, so `--no-deps` keeps the locked versions authoritative and
prevents any re-resolution. The dev lock works the same way for the unit tests,
which import the shared package and the service `app/` code.

The dev lock is a superset of `demo/requirements.txt` (the demo harness deps are
floored in `requirements-dev.in` as well), so CI installs the dev lock alone and
it covers both the unit and the integration jobs. The standalone `demo` lock
exists for running the demo on its own, per `demo/README.md`.

## Regenerating after a floor change

When you change a floor (edit a `*.in` file or `shared/pyproject.toml`),
regenerate the affected lockfile(s) and commit the floor change **and** the
regenerated lock together — a floor change that isn't recompiled is *declared but
not installed*.

Use a **clean** Python 3.12 environment (a stale venv full of older downloads can
skew resolution):

```bash
python3 -m venv /tmp/naas-lock && source /tmp/naas-lock/bin/activate
pip install pip==26.1.2 setuptools==82.0.1 pip-tools==7.5.3
```

Pin `pip` and `setuptools` alongside `pip-tools` (as above and in the CI
`lockfiles` job): `pip-compile` resolves package metadata through them, so an
unpinned upgrade can re-resolve the closure and produce a spurious diff against
an otherwise-correct lock.

Then run the compile(s) for whatever you changed (from the repo root):

```bash
pip-compile --strip-extras --output-file=requirements-dev.txt \
    requirements-dev.in shared/pyproject.toml
pip-compile --strip-extras --output-file=services/event-ingestion/requirements.txt \
    services/event-ingestion/requirements.in shared/pyproject.toml
pip-compile --strip-extras --output-file=services/identity-normalization/requirements.txt \
    services/identity-normalization/requirements.in shared/pyproject.toml
pip-compile --strip-extras --output-file=demo/requirements.txt \
    demo/requirements.in
```

A change to `shared/pyproject.toml` affects the dev lock **and both** service
locks, so recompile all three. A change to a single `*.in` affects only its own
lock.

> The `identity-normalization` compile reads `python-ldap` metadata. On a bare
> system, install its build headers first: `sudo apt-get install -y
> libldap2-dev libsasl2-dev`.

`pip-compile` keeps the existing pins unless you pass `--upgrade`, so re-running
it without a floor change produces no diff — the lock is deterministic.

> **Recompile in place.** This pin-preservation only happens when the
> `--output-file` target already exists and is read first. Always compile onto
> the committed lock (the commands above run from the repo root, so they do).
> Compiling to a *fresh* or empty path re-resolves everything to latest and will
> show large false drift — the CI `lockfiles` job recompiles in place for this
> reason.

## Guardrails

- **CI — Lockfile Drift Check.** The `lockfiles` job in
  [`.github/workflows/ci.yml`](.github/workflows/ci.yml) recompiles every
  lock and fails if the committed result differs from the floors. This catches a
  floor that was changed without regenerating its lock. Because it does not pass
  `--upgrade`, a routine upstream release never trips it — only a stale lock does.
- **Dependabot.** [`.github/dependabot.yml`](.github/dependabot.yml) opens
  CI-gated pull requests proposing newer versions. For the pip ecosystem it reads
  the `pip-compile` header in each lock and regenerates the lock with the newer
  version. It runs with **`versioning-strategy: lockfile-only`**, so a routine PR
  touches **only the `*.txt` lock** — the `*.in` / `shared/pyproject.toml` floors
  are left untouched as declared minimums. Raising a floor (declaring that the
  project now *requires* a newer version) stays a deliberate manual edit.

These are the two moments the pinned set is allowed to move: a deliberate
regenerate-and-commit, or a merged update-bot PR. A fresh install never
re-resolves on its own.

## Update policy — how the pinned set stays current

Keeping pins current is split across **two independent channels**, deliberately,
so urgent fixes are timely while routine churn stays low:

1. **Security updates — the critical, immediate channel.** GitHub opens a PR as
   soon as a [Dependabot/advisory-database](https://github.com/advisories) CVE
   affects a pinned version, regardless of the schedule below. This is the
   channel that gets security fixes in *fast*.
   - **Enable it once in the repo UI:** *Settings → Code security → Dependabot
     security updates* (it also needs *Dependabot alerts* on). This is a repo
     setting, **not** something `dependabot.yml` can turn on — so it must be
     toggled by hand (or via org policy) for the critical channel to exist.
2. **Version updates — routine freshness, low churn.** `.github/dependabot.yml`
   runs **monthly** and **grouped**, with `versioning-strategy: lockfile-only`.
   Each affected lock gets at most one batched minor+patch PR per month, touching
   only the `*.txt` (never the floors). This keeps dependencies from rotting
   toward a painful big-bang upgrade, without a PR per point release.

**Why not "only significant bug fixes"?** Dependabot has no notion of a bugfix's
*significance* — it only knows version numbers and security advisories. Security
advisories are therefore the precise "this is critical, ship it now" signal; the
monthly version sweep is just freshness you can skim, merge, or skip.

**Manual levers** (the deliberate moves no bot makes for you):

- **Raise a floor** when the project genuinely starts to *require* a newer
  release (you depend on a feature/fix added in it): edit the `*.in` /
  `shared/pyproject.toml`, regenerate, and commit (see *Regenerating* above).
  That is a human judgment, not a mechanical bump.
- **Deep refresh** (optional): to move the *whole* pinned set forward beyond
  what the monthly sweep proposes, re-run the compile commands above with
  `--upgrade` in a clean env, review, and commit — e.g. on a quarterly cadence.

> Note: the pip config watches several directories that share
> `shared/pyproject.toml`, so a bump to a shared dependency can produce one PR
> per affected lock (grouping bundles packages *within* a directory, but cannot
> merge *across* directories). Monthly cadence keeps that fan-out infrequent.
