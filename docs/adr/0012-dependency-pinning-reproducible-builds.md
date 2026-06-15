# 12. Pin Python Dependencies via Compiled Lockfiles for Reproducible Builds

* Status: accepted
* Date: 2026-06-15
* Deciders: Tony

## Context and Problem Statement

NAAS declares its Python dependencies as minimum-version floors (`>=`). The runtime dependencies of both services live in `shared/pyproject.toml` (installed into each service image and the dev venv via an editable install of the `shared/` package), and each service's thin `requirements.txt` adds its web-server and protocol libraries the same way. The dev and test toolchain (`requirements-dev.txt`, `demo/requirements.txt`) is exact-pinned, but the runtime floors it pulls in transitively are not.

Floors express the *minimum* version the project supports, not the version that actually gets installed. A fresh environment — a CI runner, a freshly built image, a new contributor's venv — resolves each floor to the newest compatible release available at install time. Two builds weeks apart can therefore ship different minor versions of the same library from identical source. This is not hypothetical: a routine upstream release of a floored dependency changed the shape of a return value and broke the test suite on a fresh CI runner, even though nothing in the repository had changed.

The project needs a deliberate reproducibility posture: the same source must produce the same installed dependency set in every environment, while still leaving a controlled path for security and bug-fix updates.

## Decision Drivers

* Builds must be reproducible — identical source resolves to an identical dependency set across the dev venv, CI, and every service image.
* Exact pins on *direct* dependencies are insufficient: transitive dependencies still float, so the same class of silent breakage can recur through a sub-dependency.
* Dependencies must not be frozen forever — security patches and bug fixes need a controlled way in.
* The declared minimum-version intent (the floors) is useful information and should be preserved, not discarded.
* The runtime install mechanics are plain `pip install` in both the Dockerfiles and CI; the chosen approach should not force a heavier toolchain onto the install path.
* Service images and the dev venv must stay consistent with one another, so the posture has to be applied repo-wide in one pass.

## Considered Options

* **Compiled lockfiles generated from the floors, via pip-tools** (chosen): keep the floors as compile inputs; `pip-compile` resolves them into fully-pinned lockfiles that capture the entire transitive closure; every environment installs from the lockfiles.
* **Bare `==` pins on direct dependencies**: rewrite each floor as an exact pin in place, with no lockfile.
* **Compiled lockfiles via uv**: the same lockfile model using the `uv` toolchain instead of pip-tools.
* **Status quo (floors only)**: continue resolving floors at install time in every environment.

## Decision Outcome

Chosen option: **compiled lockfiles generated from the floors with pip-tools.**

The floors remain the human-authored statement of declared compatibility and serve as the compile inputs. `pip-compile` resolves them — once, deliberately — into fully-pinned lockfiles that pin the complete transitive closure to exact versions. The lockfile produced by that first compile is a point-in-time snapshot of the latest-compatible resolution and becomes the artifact every environment installs from: the dev venv, CI, and each service image all install the same locked set. Because pip-tools emits a plain pip-installable requirements file, the install path stays `pip install -r <lockfile>` and no new tooling is forced onto the Dockerfiles or CI runners.

Pins are kept current under review rather than by drift: an automated dependency-update bot (Dependabot) opens pull requests proposing newer versions, so security and bug-fix updates surface as reviewable, CI-gated changes. Re-resolution is a deliberate act — regenerating the lockfiles — never an implicit consequence of a fresh install.

The posture is applied repo-wide in a single pass so the service images and the dev venv cannot diverge.

### Positive Consequences

* Identical source produces an identical installed dependency set in every environment; the nondeterministic-build failure mode is closed.
* The entire transitive closure is pinned, so a silent sub-dependency bump can no longer change behavior between builds — the exact failure that motivated this decision cannot recur unreviewed.
* The runtime install path is unchanged: plain `pip install -r` against a generated requirements file.
* The floors survive as readable, declared-minimum intent; the exact versions are generated, not hand-curated, so there is no hand-maintained list of pins to keep accurate.
* Updates remain available and controlled — the update bot proposes them, CI vets them, a human merges them.

### Negative Consequences

* Changing a dependency now has an extra step: regenerate the lockfiles and commit the result. Forgetting it means the change is declared but not installed.
* Lockfiles enlarge dependency diffs — a one-line floor change can produce a many-line lockfile delta.
* The update bot generates a stream of pull requests that must be triaged.
* pip-tools is an added development-time tool and a compile step contributors must learn.

### Conditions for Revisiting

If the multi-package layout — per-service locks that must each subsume the shared package's closure — makes the compile workflow slow or awkward, revisit uv, whose workspace handling and compile speed address exactly that friction. The lockfile-as-install-artifact principle would carry over unchanged; only the tool that produces the locks would differ.

## Pros and Cons of the Options

### Compiled lockfiles via pip-tools

* Good, because it pins the full transitive closure, giving true build reproducibility rather than direct-dependency-only pinning.
* Good, because the floors are retained as inputs, preserving declared-minimum intent while the exact set is generated.
* Good, because the output is a plain pip-installable file, so Dockerfiles and CI keep their existing `pip install -r` step.
* Good, because pip-tools is a long-established, widely recognized tool with a minimal conceptual surface.
* Bad, because it adds a regenerate-and-commit step and enlarges dependency diffs.

### Bare `==` pins on direct dependencies

* Good, because it is the simplest change — rewrite each floor as an exact version in place.
* Good, because it makes the directly-declared versions deterministic.
* Bad, because transitive dependencies still float, so the motivating failure class can recur through a sub-dependency — it does not actually deliver reproducible builds.
* Bad, because keeping the exact pins accurate becomes manual work spread across several files with no single generated source.

### Compiled lockfiles via uv

* Good, because it delivers the same full-closure reproducibility as pip-tools, and faster.
* Good, because it handles multi-package/workspace resolution more natively.
* Good, because its compiled output is still pip-installable, so the install path need not change.
* Bad, because it introduces a newer, less universally familiar tool when pip-tools already meets the requirement, so it is held in reserve rather than adopted now.

### Status quo (floors only)

* Good, because it requires no work and keeps dependency declarations minimal.
* Bad, because every fresh environment can resolve to a different version set, which already broke CI from unchanged source.
* Bad, because it offers no reproducibility guarantee for builds, demos, or contributor environments.

## More Information

The floors are the compile inputs; the generated lockfiles are the install artifacts. CI, the service images, and the dev venv all install from the lockfiles, so they resolve to one identical dependency set. The editable install of the in-repo shared package is retained for local development, but its third-party dependencies are pinned by the same lockfiles rather than re-resolved at install time. Regenerating the lockfiles after changing a floor, and merging the update bot's proposals, are the two deliberate moments at which the pinned set is allowed to move.
