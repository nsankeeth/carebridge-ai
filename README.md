# CareBridge

AI medical navigation and clinician handoff agent, powered by Meta models.

Patient uploads a lab PDF → Meta model extracts and explains it → patient consents → coordinator agent hands it to
a clinician via tools → clinician reviews → follow-up agent chases open items → everything audited.

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

Seed demo data (runs the real Meta pipeline on 5 reports):

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

Open http://localhost:3000. The login page has one-click demo accounts (patient, clinician, admin);
the shared demo password is `DEMO_PASSWORD` in `backend/app/seed.py`. API docs: http://localhost:8000/docs.

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
