# CareBridge

AI medical navigation and clinician handoff agent, powered by Meta models.

A patient or parent describes what's wrong → red-flag rules and a Meta model set the urgency (Call 911 immediately
when it may be an emergency) → the family doctor and on-call clinicians are paged and escalated until someone
responds → the clinician reads a grounded Meta-drafted brief and replies or calls. Lab PDFs attached in a thread are
read and explained by Meta, every value checked against the PDF. Everything is audited.

## Quick start

Requires Docker, Python 3.13, Node 20+.

```bash
cp .env.example .env            # then set MODEL_API_KEY (Meta Model API key)
docker compose up -d db
cd backend && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt && .venv/bin/alembic upgrade head && cd ..
cd frontend && npm install && cd ..
```

Verify real Meta inference (structured output + tool calling):

```bash
cd backend && .venv/bin/python -m app.verify_meta
```

Seed synthetic data (runs the real Meta pipeline on 5 reports and 2 symptom threads; requires `MODEL_API_KEY`):

```bash
cd backend && .venv/bin/python -m app.seed
```

Run:

```bash
./scripts/dev-backend.sh
```

```bash
./scripts/dev-frontend.sh
```

Open http://localhost:3000. The login page has one-click synthetic demo accounts (patient, clinician, admin);
the shared demo password is `DEMO_PASSWORD` in `backend/app/seed.py`. API docs: http://localhost:8000/docs.

Live triage evaluation on 15 synthetic vignettes:

```bash
cd backend && .venv/bin/python -m app.triage.eval
```

## Tests

```bash
docker compose exec -T db psql -U medhandoff -c "CREATE DATABASE medhandoff_test"   # once
cd backend && .venv/bin/python -m pytest
```

```bash
cd frontend && npx playwright install chromium && npx playwright test   # servers must be running and seeded
```

## Docs

- [Architecture & Meta model usage](docs/ARCHITECTURE.md)
- [Security, privacy & clinical safety](docs/SECURITY_AND_SAFETY.md)
- [Test results](docs/TEST_RESULTS.md)
- [AWS deployment](docs/DEPLOYMENT_AWS.md)
