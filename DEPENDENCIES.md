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
  | `requirements-dev.txt` | `requirements-dev.in` (pins shared via `./shared`) | CI unit + integration jobs |
  | `services/event-ingestion/requirements.txt` | that service's `requirements.in` (pins shared via `../../shared`) | `services/event-ingestion/Dockerfile` |
  | `services/identity-normalization/requirements.txt` | that service's `requirements.in` (pins shared via `../../shared`) | `services/identity-normalization/Dockerfile` |
  | `demo/requirements.txt` | `demo/requirements.in` | `demo/README.md` |

Each lock that needs shared lists it as a local path dependency in its `.in`, so
the lock pins **shared's entire transitive closure**, not just the service's own
two or three lines. That path is the *only* compile input — shared itself is
suppressed from the lock with `--unsafe-package=naas-shared` (a local path is not
a portable pin; `pip` and `setuptools` are suppressed the same way as build
backends). A single input is deliberate (see the callout below). Folding shared
in as a path dep keeps the closure inside a `.in` input Dependabot does compile,
while the suppression flags survive in the header. The service images install the
lock first, then the shared package editable with `pip install -e shared/
--no-deps` — the lock already pins shared's dependencies, so `--no-deps` keeps the
locked versions authoritative and prevents any re-resolution. The dev lock works
the same way for the unit tests, which import the shared package and the service
`app/` code.

> **The path is written relative to each `.in` file's own directory**, and the
> lock is compiled from that directory, because Dependabot resolves a path-based
> dependency relative to the manifest's directory (not the repo root). So
> `requirements-dev.in`, at the repo root, points to `./shared`; the service
> `.in` files, two levels down, point to `../../shared`. A root-relative
> `./shared` in a service `.in` compiles fine from the repo root but leaves
> Dependabot unable to fetch it (it looks for `services/<svc>/shared`, which does
> not exist) — silently blocking that lock's security and version PRs. The
> regen commands below compile each service lock from its own directory for this
> reason.

> **⚠️ Do not "simplify" this back to the two-input form**
> (`pip-compile … <service>/requirements.in shared/pyproject.toml`). It looks
> tidier and compiles to the same lock by hand, but it silently breaks Dependabot.
> When Dependabot regenerates a lock it does **not** replay the header's command.
> It splits the two concerns:
> - **Inputs** come only from the dependency's `*.in` files (it filters
>   `filenames_to_compile` to `*.in`) — *never* from the header's positional args.
>   A `shared/pyproject.toml` passed positionally is invisible to it, so the whole
>   shared closure (fastapi, pydantic, sqlalchemy, …) is dropped from the
>   regenerated lock. This actually happened — see the history of this file.
> - **Options** (`--unsafe-package`, `--strip-extras`, `--generate-hashes`, …) are
>   re-derived by regex-scanning the committed lock's header comment lines. The
>   `--unsafe-package` scan is a `.scan().uniq`, so all three of ours survive.
>
> The shared path dependency lives in a `.in` (an input Dependabot compiles)
> and the `--unsafe-package` flags live in the header (which it scans), so both
> halves of the lock regenerate correctly. The two-input form satisfies neither.

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

Then run the compile(s) for whatever you changed — from the repo root, except the
service locks, which compile from their own directory (their `.in` lists shared as
`../../shared`, relative to the manifest dir the way Dependabot resolves path deps,
which only resolves when pip-compile runs from that directory too):

```bash
UNSAFE="--unsafe-package=naas-shared --unsafe-package=pip --unsafe-package=setuptools"
pip-compile --strip-extras $UNSAFE \
    --output-file=requirements-dev.txt requirements-dev.in
( cd services/event-ingestion && pip-compile --strip-extras $UNSAFE \
    --output-file=requirements.txt requirements.in )
( cd services/identity-normalization && pip-compile --strip-extras $UNSAFE \
    --output-file=requirements.txt requirements.in )
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
> the committed lock — the commands above do, whether run from the repo root or,
> for the service locks, from the service directory (where `requirements.txt`
> already exists). Compiling to a *fresh* or empty path re-resolves everything to
> latest and will show large false drift — the CI `lockfiles` job recompiles in
> place for this reason.

## Guardrails

- **CI — Lockfile Drift Check.** The `lockfiles` job in
  [`.github/workflows/ci.yml`](.github/workflows/ci.yml) recompiles every
  lock and fails if the committed result differs from the floors. This catches a
  floor that was changed without regenerating its lock. Because it does not pass
  `--upgrade`, a routine upstream release never trips it — only a stale lock does.
- **CI — Dependency Audit (pip-audit).** The `audit` job in [`.github/workflows/ci.yml`](.github/workflows/ci.yml) runs a pinned `pip-audit --no-deps` over every compiled lockfile on each push/PR and fails on any published advisory against a pinned version. It is the in-repo, blocking complement to the Dependabot security channel below (which is a repo-UI toggle and acts asynchronously): CI itself refuses to stay green while a shipped pin carries a known CVE. Fix by taking the advisory's version (bump the floor if needed), regenerating the lock, and committing.
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
