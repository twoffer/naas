# Feature Implementer Memory

## Project
- [project_naas_shared_config_extra_ignore.md](project_naas_shared_config_extra_ignore.md) — Settings class needs extra="ignore"; repo .env contains undeclared vars that cause pydantic-settings to raise
- [project_httpx_test_dep.md](project_httpx_test_dep.md) — httpx not in venv by default; starlette.testclient requires it; install if TestClient tests fail with ModuleNotFoundError

## Patterns
- [patterns_health_patch.md](patterns_health_patch.md) — /health must access naas_shared.database and naas_shared.redis_client via module refs at call time for test patches to work; Depends() won't work with module-level patches

## Patterns
- [patterns_utc_timestamp_defense.md](patterns_utc_timestamp_defense.md) — Three-layer UTC pin: Pydantic validator + DateTime(timezone=True) ORM + engine connect_args. Events table only; other tables stay TIMESTAMP.

## Patterns
- [patterns_service_test_isolation.md](patterns_service_test_isolation.md) — Per-service conftest.py required to isolate app.* sys.modules when multiple service test dirs share same-named test files; also update spec_0 IMPLEMENTED_APP_SERVICES registry
- [patterns_fastapi_oauth2_redirect.md](patterns_fastapi_oauth2_redirect.md) — Set swagger_ui_oauth2_redirect_url=None on FastAPI() to suppress hidden /docs/oauth2-redirect route that breaks chunk-1 scope boundary tests

## Patterns
- [patterns_ldap_dn_no_native.md](patterns_ldap_dn_no_native.md) — python-ldap can't pip-install in dev venv (no gcc); use regex for DN parsing in tests

## Patterns
- [patterns_get_redis_mock_seam.md](patterns_get_redis_mock_seam.md) — Use inspect.isawaitable() when calling get_redis(); chunk-4 tests patch with MagicMock(return_value=fake_redis) which returns fake_redis directly (not a coroutine)
- [patterns_ldap_filter_parens_test_conflict.md](patterns_ldap_filter_parens_test_conflict.md) — Two-tier LDAP filter building: public build_search_filter (with parens) and internal _build_search_filter_internal (without parens) to satisfy both RFC and metacharacter sanitization tests

## Patterns
- [patterns_tempfile_flush_conftest.md](patterns_tempfile_flush_conftest.md) — Test helpers calling load_config() inside a NamedTemporaryFile with block need a conftest flush-on-write autouse fixture to prevent reading an empty file

## Patterns
- [patterns_ldap_dn_str2dn_fallback.md](patterns_ldap_dn_str2dn_fallback.md) — _reduce_dn_to_group_name: str2dn primary + regex fallback on ImportError to keep dev-venv (no gcc/python-ldap) tests green
- [patterns_consumer_loop_resilience.md](patterns_consumer_loop_resilience.md) — xreadgroup outer loop: except Exception catches transient errors, CancelledError propagates; truncate str(exc)[:200] at all log sites for PII safety

## Feedback
- [feedback_ruff_format_test_files.md](feedback_ruff_format_test_files.md) — ruff format must be applied to test files, not just ruff check
