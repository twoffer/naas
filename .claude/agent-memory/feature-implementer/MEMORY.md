# Feature Implementer Memory

## Project
- [project_naas_shared_config_extra_ignore.md](project_naas_shared_config_extra_ignore.md) — Settings class needs extra="ignore"; repo .env contains undeclared vars that cause pydantic-settings to raise
- [project_httpx_test_dep.md](project_httpx_test_dep.md) — httpx not in venv by default; starlette.testclient requires it; install if TestClient tests fail with ModuleNotFoundError

## Patterns
- [patterns_health_patch.md](patterns_health_patch.md) — /health must access naas_shared.database and naas_shared.redis_client via module refs at call time for test patches to work; Depends() won't work with module-level patches

## Patterns
- [patterns_utc_timestamp_defense.md](patterns_utc_timestamp_defense.md) — Three-layer UTC pin: Pydantic validator + DateTime(timezone=True) ORM + engine connect_args. Events table only; other tables stay TIMESTAMP.

## Feedback
- [feedback_ruff_format_test_files.md](feedback_ruff_format_test_files.md) — ruff format must be applied to test files, not just ruff check
