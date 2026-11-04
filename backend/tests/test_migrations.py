import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

BACKEND = Path(__file__).resolve().parents[1]


def alembic(url: str, *args: str) -> None:
    env = {**os.environ, "DATABASE_URL": url}
    r = subprocess.run([sys.executable, "-m", "alembic", *args], cwd=BACKEND, env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-2000:]


@pytest.fixture
def empty_db_url():
    base = make_url(os.environ["DATABASE_URL"])
    name = f"migcheck_{uuid.uuid4().hex[:8]}"
    admin = create_engine(base, isolation_level="AUTOCOMMIT")
    with admin.connect() as c:
        c.execute(text(f'CREATE DATABASE "{name}"'))
    try:
        yield base.set(database=name).render_as_string(hide_password=False)
    finally:
        with admin.connect() as c:
            c.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()


def test_migrations_upgrade_downgrade_to_empty_and_upgrade_again(empty_db_url):
    alembic(empty_db_url, "upgrade", "head")
    alembic(empty_db_url, "downgrade", "base")
    engine = create_engine(empty_db_url)
    with engine.connect() as c:
        leftover = c.execute(text("select typname from pg_type t join pg_namespace n on n.oid = t.typnamespace where n.nspname = 'public' and t.typtype = 'e'")).scalars().all()
    engine.dispose()
    assert leftover == []
    alembic(empty_db_url, "upgrade", "head")
