import os

os.environ["APP_ENV"] = "test"
# Never fall back to DATABASE_URL: the suite truncates every table.
os.environ["DATABASE_URL"] = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+asyncpg://crm:crm-dev-password@postgres:5432/crm_test")
assert os.environ["DATABASE_URL"].rsplit("/", 1)[-1].endswith("_test"), "tests must run against a *_test database"
os.environ["FINANCE_INTERNAL_URL"] = "http://finance.test"
os.environ["DEMO_MODE"] = "false"
os.environ["CRM_INTEGRATION_SECRET"] = "test-integration-secret"

import pytest  # noqa: E402
import respx  # noqa: E402
from httpx import ASGITransport, AsyncClient, Response  # noqa: E402

KEEP = {"alembic_version", "training_programs", "settings"}

# Pure unit tests (no fixtures below) never touch the database, so they can
# run anywhere and in parallel. Only `db`, `client` and `migrated` need Postgres.


@pytest.fixture(scope="session")
def migrated():
    from alembic import command
    from alembic.config import Config
    here = os.path.dirname(__file__)
    cfg = Config(os.path.join(here, "..", "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(here, "..", "alembic"))
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    yield cfg


@pytest.fixture
async def clean_db(migrated):
    from sqlalchemy import text

    from app.core import auth as auth_mod
    from app.core.db import sessionmaker
    auth_mod._cache.clear()
    auth_mod._client = None
    from app.core.security import window
    window.reset()
    async with sessionmaker()() as db:
        tables = [r[0] for r in await db.execute(text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'"))]
        wipe = [t for t in tables if t not in KEEP]
        if wipe:
            await db.execute(text(f"TRUNCATE {', '.join(wipe)} RESTART IDENTITY CASCADE"))
        # settings.updated_by_id → users, so the CASCADE above empties settings; restore the defaults.
        import json

        from app.services.defaults import DEFAULT_SETTINGS
        await db.execute(text("DELETE FROM settings"))
        for key, value in DEFAULT_SETTINGS.items():
            await db.execute(text("INSERT INTO settings (key, value, version) VALUES (:k, CAST(:v AS jsonb), 1)"),
                             {"k": key, "v": json.dumps(value)})
        await db.commit()
    yield


@pytest.fixture
async def db(clean_db):
    from app.core.db import sessionmaker
    async with sessionmaker()() as session:
        yield session


@pytest.fixture
async def client(clean_db):
    from app.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://sales.test") as c:
        yield c


@pytest.fixture
def finance():
    with respx.mock(base_url="http://finance.test", assert_all_called=False) as mock:
        yield mock


def finance_session(finance, username="owner", role="director", caps=("crm", "invoices"), token="tok-1"):
    """Make the fake Finance accept `token` as a session for `username`."""
    def me(request):
        if request.headers.get("cookie", "") != f"cnc_session={token}":
            return Response(401, json={"detail": "Not authenticated"})
        return Response(200, json={"id": 1, "username": username, "role": role, "caps": list(caps)})
    finance.get("/api/me").mock(side_effect=me)
    return {"cnc_session": token}
