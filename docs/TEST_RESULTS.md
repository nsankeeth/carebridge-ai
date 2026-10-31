# Test Results

All results below were produced by actually running the suites on 2026-11-02 (macOS, Python 3.13.7, Node 24,
Postgres 16 in Docker).

## Live Meta inference: verified

`cd backend && .venv/bin/python -m app.verify_meta`

```
endpoint=https://api.meta.ai/v1 model=muse-spark-1.3 key_configured=True
[structured] ok model=muse-spark-1.3 latency=10721ms tokens=774/1286/2060
   - Hemoglobin: 112 g/L (ref 120-160) flag=L p1
   - Hematocrit: 0.35 L/L (ref 0.36-0.46) flag=L p1
   - MCV: 76 fL (ref 80-100) flag=L p1
   - White Blood Cells: 6.4 x10^9/L (ref 4.0-11.0) flag=None p1
   - Platelets: 288 x10^9/L (ref 150-400) flag=None p1
   - Ferritin: 9 ug/L (ref 15-150) flag=L p1
[tools] ok model=muse-spark-1.3 latency=751ms tokens=1181 tool_calls=['get_case_snapshot']
Meta inference verified.
```

Seeding with live inference (`python -m app.seed`): 5 reports × 3 Meta calls = 15/15 ok, latency 3.5–18 s per call,
5/5 summaries passed grounding + safety validation on the first attempt. Reviewing the metabolic report: the
explanation described both flagged glucose results without naming a condition.

Follow-up agent on live Meta (4 candidate cases): took no action on the 3 that needed none; on the handoff left
unacknowledged past 24 h it called `create_follow_up_task(ack_reminder)` and `notify_clinician`. Session total:
25 Meta calls, 25 ok, ~63k tokens.

## Backend: `cd backend && .venv/bin/python -m pytest`

Result: **37 passed** (≈60 s). Uses a deterministic test double for the model so tests are fast and offline.

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
| Agent guardrails | messages with medical details blocked (7 cases incl. durations allowed); unknown tools refused; agent that skips the handoff → run FAILED |

## End-to-end: `cd frontend && npx playwright test`

Result: **2 passed against live Meta** (≈52 s; journey 47 s).

1. Full journey: patient login → upload → processing → findings (exact values) → explanation → consent →
   agent handoff (trace shows `create_clinician_handoff`) → clinician login → acknowledge → start review →
   assess → decision + next step → complete → patient sees outcome; clinical notes not visible to patient.
2. A clinician gets 403 (API) and an error page (UI) for a patient case that wasn't shared with them.

## Defects found and fixed

| Found by | Defect | Fix |
|---|---|---|
| Live Meta run | `notify_clinician` refused right after the agent created the handoff (stale ORM relationship) | Query the handoff from the DB; regression test reproduces the live tool order and was confirmed failing on the old code |
| Live Meta run | Admin-message filter rejected "24 hours" (any digit) and "past" (matched `ast`) | Word boundaries; durations allowed; parametrized tests |
| Test run | Suite hung: sessions left open blocked TRUNCATE | Close all sessions before each test |
| E2E | Isolation test skipped after re-seed (no unshared case) | Test now creates its own unshared case |
