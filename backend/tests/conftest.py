import os
import tempfile

os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL", "postgresql+psycopg://medhandoff:medhandoff@localhost:5433/medhandoff_test")
os.environ["STORAGE_DIR"] = tempfile.mkdtemp(prefix="carebridge-test-")

from collections.abc import Iterator  # noqa: E402
from typing import Any  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.orm import close_all_sessions  # noqa: E402

from app.ai.provider import CallMeta, set_provider_override  # noqa: E402
from tests import fake_outputs  # noqa: E402
from app.db import Base, SessionLocal, engine  # noqa: E402
from app.fixtures import REPORTS, build_pdf  # noqa: E402
from app.main import app  # noqa: E402
from app.models import ClinicianProfile, Organization, PatientProfile, User, UserRole  # noqa: E402
from app.security import hash_password  # noqa: E402

PASSWORD = "test-password-1"


class FakeProvider:
    """Deterministic test double so tests never hit the network. Tests patch `overrides` to inject bad model output."""

    name = "fake"
    model_id = "fake-model"
    overrides: dict[str, Any] = {}

    def _meta(self, task: str) -> CallMeta:
        return CallMeta(task=task, provider=self.name, model_id=self.model_id)

    def tool_step(self, *, task, messages, tools, context=None):
        return fake_outputs.tool_step(messages, context or {}), self._meta(task)

    def structured(self, *, task, system, user, schema, context=None):
        if task in self.overrides:
            o = self.overrides[task]
            o = o(context) if callable(o) else o
            if isinstance(o, Exception):
                raise o
            return schema.model_validate(o), self._meta(task)
        return schema.model_validate(fake_outputs.structured(task, context or {})), self._meta(task)


@pytest.fixture(scope="session", autouse=True)
def schema() -> Iterator[None]:
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield
    engine.dispose()


@pytest.fixture(autouse=True)
def clean_db() -> Iterator[None]:
    FakeProvider.overrides = {}
    set_provider_override(FakeProvider)
    close_all_sessions()  # sessions left open by earlier tests would block TRUNCATE
    with engine.begin() as conn:
        conn.execute(text("TRUNCATE " + ", ".join(t.name for t in reversed(Base.metadata.sorted_tables)) + " RESTART IDENTITY CASCADE"))
    yield
    set_provider_override(None)


@pytest.fixture
def people() -> dict[str, dict[str, str]]:
    db = SessionLocal()
    org = Organization(name="Test Org")
    db.add(org)
    db.flush()
    out: dict[str, dict[str, str]] = {}
    for key, role in [("patient_a", UserRole.PATIENT), ("patient_b", UserRole.PATIENT), ("clin_a", UserRole.CLINICIAN), ("clin_b", UserRole.CLINICIAN), ("admin", UserRole.ADMIN)]:
        u = User(org_id=org.id, email=f"{key}@test.demo", full_name=key.replace("_", " ").title(), role=role, password_hash=hash_password(PASSWORD))
        db.add(u)
        db.flush()
        profile_id = None
        if role == UserRole.PATIENT:
            p = PatientProfile(user_id=u.id, province="ON")
            db.add(p)
            db.flush()
            profile_id = p.id
        elif role == UserRole.CLINICIAN:
            c = ClinicianProfile(user_id=u.id, specialty="Family Medicine", clinic_name="Test Clinic")
            db.add(c)
            db.flush()
            profile_id = c.id
        out[key] = {"email": u.email, "user_id": str(u.id), "profile_id": str(profile_id) if profile_id else ""}
    db.commit()
    db.close()
    return out


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def login(client: TestClient, email: str) -> dict[str, str]:
    r = client.post("/api/auth/login", json={"email": email, "password": PASSWORD})
    assert r.status_code == 200, r.text
    client.cookies.clear()  # tests authenticate with explicit bearer headers per role
    return {"Authorization": f"Bearer {r.json()['token']}"}


@pytest.fixture
def auth(client: TestClient, people):
    return {k: login(client, v["email"]) for k, v in people.items()}


def report_pdf(slug: str = "cbc-iron-maya") -> bytes:
    return build_pdf(next(r for r in REPORTS if r.slug == slug))


def upload(client: TestClient, headers: dict[str, str], slug: str = "cbc-iron-maya") -> dict:
    r = client.post("/api/patient/cases/upload", headers=headers, data={"title": "Blood work"}, files={"file": (f"{slug}.pdf", report_pdf(slug), "application/pdf")})
    assert r.status_code == 201, r.text
    case_id = r.json()["case"]["id"]
    return client.get(f"/api/patient/cases/{case_id}", headers=headers).json()


def share(client: TestClient, auth, people, case_id: str, clinician: str = "clin_a") -> None:
    h = auth["patient_a"]
    assert client.post(f"/api/patient/cases/{case_id}/consent/request", headers=h).status_code == 200
    r = client.post(f"/api/patient/cases/{case_id}/consent", headers=h, json={"clinician_id": people[clinician]["profile_id"], "confirmed": True})
    assert r.status_code == 200, r.text
    r = client.post(f"/api/patient/cases/{case_id}/handoff", headers=h)
    assert r.status_code == 202, r.text
