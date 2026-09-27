"""E19: the in-process gateway these tests build runs on the managed PostgreSQL schema whenever
TEST_ORG_DATABASE_URL is set, exactly as the Platform suite does."""
try:
    from project_gateway.tests.conftest import managed_engine  # noqa: F401
except ImportError:  # the Platform test runtime is optional outside the gateway lane
    pass
