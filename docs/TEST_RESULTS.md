# Test Results

All results below were produced by actually running the suites on 2026-11-02 (macOS, Python 3.13.7, Node 24,
Postgres 16 in Docker).

**Important:** the backend runs use a deterministic test double for the model. They verify workflow, validation,
authorization and UI. They don't verify Meta inference quality. Live Meta verification (`python -m app.verify_meta`)
is **pending an API key**.

## Backend: `cd backend && .venv/bin/python -m pytest`

Result: **29 passed** (≈56 s).

| Area | Tests |
|---|---|
| Authentication | login, wrong password, unauthenticated rejection, logout invalidates token, cookie session |
| Role authorization | patient→clinician API, clinician→admin API, admin→patient API all 403 |
| Patient isolation | another patient's case, findings, explanation, document, sharing, consent all 404 |
| Clinician authorization | unshared case 403; shared with A, B gets 403; withdrawn consent revokes access |
| Admin data minimization | overview contains no test names; admin can't open clinician case view |
| Document upload | non-PDF rejected, >10 MB rejected, valid PDF processed |
| Finding extraction | exact value/unit/range/flag/page/date preserved; parser handles `<`, `>`, digits in names |
| Grounding | altered value and invented test marked NEEDS_REVIEW; missed rows recovered from source |
| AI output validation | schema-invalid output retried then PROCESSING_FAILED with no summary; API error fails then retry succeeds; diagnostic + medication language → NEEDS_CORRECTION and sharing blocked; summary/report contradiction caught |
| Telemetry | every model call logged with task, model id, status |
| Consent enforcement | handoff without consent 409 (API) and refused (agent tool); explicit confirmation required |
| Clinician handoff | agent tool sequence, acknowledge → review → assessment required → complete; patient sees next step but not clinical notes; audit actions present |
| Duplicate handoffs | 3 requests + direct service call → 1 handoff |
| Workflow transitions | invalid transitions raise; every status has a transition entry |
| Follow-up | overdue handoff → one `ack_reminder` across two agent runs; clinician notified; acknowledging closes it |
| Agent guardrails | messages with medical details blocked; unknown tools refused; agent that skips the handoff → run FAILED, not silent success |

## End-to-end: `cd frontend && npx playwright test`

Result: **not yet run**. Needs live Meta inference (pending an API key). Two journeys are written:

1. Full journey: patient login → upload → processing → findings (exact values) → explanation → consent →
   agent handoff (trace shows `create_clinician_handoff`) → clinician login → acknowledge → start review →
   assess → decision + next step → complete → patient sees outcome; clinical notes not visible to patient.
2. A clinician gets 403/404 on a patient case that wasn't shared with them.

## Pending

- [ ] `python -m app.verify_meta` with a real key (structured output + tool calling)
- [ ] Re-seed with real inference and run the Playwright journeys against live Meta
