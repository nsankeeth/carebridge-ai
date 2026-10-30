from tests.conftest import PASSWORD, login, share, upload


def test_login_and_me(client, people):
    h = login(client, people["patient_a"]["email"])
    r = client.get("/api/auth/me", headers=h)
    assert r.status_code == 200
    assert r.json()["role"] == "PATIENT"


def test_wrong_password_rejected(client, people):
    r = client.post("/api/auth/login", json={"email": people["patient_a"]["email"], "password": "nope"})
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "invalid_credentials"


def test_unauthenticated_requests_rejected(client):
    assert client.get("/api/auth/me").status_code == 401
    assert client.get("/api/patient/cases").status_code == 401
    assert client.get("/api/auth/me", headers={"Authorization": "Bearer not-a-token"}).status_code == 401


def test_logout_invalidates_token(client, people):
    h = login(client, people["patient_a"]["email"])
    assert client.post("/api/auth/logout", headers=h).status_code == 200
    assert client.get("/api/auth/me", headers=h).status_code == 401


def test_cookie_session_login(client, people):
    r = client.post("/api/auth/login", json={"email": people["clin_a"]["email"], "password": PASSWORD})
    assert "mh_session" in r.cookies
    assert client.get("/api/auth/me").json()["role"] == "CLINICIAN"


def test_roles_are_enforced(client, auth):
    assert client.get("/api/clinician/cases", headers=auth["patient_a"]).status_code == 403
    assert client.get("/api/admin/overview", headers=auth["clin_a"]).status_code == 403
    assert client.get("/api/patient/cases", headers=auth["admin"]).status_code == 403


def test_patient_cannot_access_another_patients_report(client, auth):
    case = upload(client, auth["patient_a"])
    other = auth["patient_b"]
    for path in ("", "/findings", "/explanation", "/document", "/sharing", "/handoff"):
        assert client.get(f"/api/patient/cases/{case['id']}{path}", headers=other).status_code == 404, path
    assert client.post(f"/api/patient/cases/{case['id']}/consent/request", headers=other).status_code == 404
    assert client.get("/api/patient/cases", headers=other).json() == []


def test_clinician_cannot_access_unassigned_case(client, auth, people):
    case = upload(client, auth["patient_a"])
    # Not shared with anyone yet.
    assert client.get(f"/api/clinician/cases/{case['id']}", headers=auth["clin_a"]).status_code == 403
    share(client, auth, people, case["id"], "clin_a")
    assert client.get(f"/api/clinician/cases/{case['id']}", headers=auth["clin_a"]).status_code == 200
    # Shared with clin_a only.
    assert client.get(f"/api/clinician/cases/{case['id']}", headers=auth["clin_b"]).status_code == 403
    assert client.get(f"/api/clinician/cases/{case['id']}/document", headers=auth["clin_b"]).status_code == 403
    assert client.post(f"/api/clinician/cases/{case['id']}/acknowledge", headers=auth["clin_b"]).status_code == 403
    assert client.get("/api/clinician/cases", headers=auth["clin_b"]).json() == []


def test_admin_overview_contains_no_clinical_content(client, auth, people):
    case = upload(client, auth["patient_a"])
    body = client.get("/api/admin/overview", headers=auth["admin"]).text
    assert case["id"] in body
    for f in case["findings"]:
        assert f["test_name"] not in body
    assert client.get(f"/api/clinician/cases/{case['id']}", headers=auth["admin"]).status_code == 403
