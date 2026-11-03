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

## Symptom threads on live Meta

Manual run in the browser (Maya → Ava, the vomiting/lethargy message): the rules set **Urgent** and paged Dr. Raman
(family doctor) and Dr. Tremblay (on call) in the same request. Meta's triage call took 35 s and returned URGENT
with two grounded red flags (`child_lethargy`, `child_refusing_fluids`), a safe acknowledgement and three tap
questions; the clinician brief took 30 s, with zero ungrounded quotes dropped. Tapping **No** to "Can they be woken
easily?" showed the Call 911 screen in under 1.5 s. Dr. Raman's queue showed the thread first with a countdown;
replying auto-acknowledged and moved it to "In conversation".

Seeding (`python -m app.seed`) now also runs two symptom threads through live Meta: Ava's → URGENT, paged, response
due 15 min after seeding; Daniel's two-week cough → ROUTINE, then acknowledged and answered by Dr. Tremblay.

### Live triage evaluation: `python -m app.triage.eval`

15 synthetic vignettes, each with a minimum expected level, run through the rules and `muse-spark-1.3`. First run
(2026-11-02, before the rule fix below):

```
vignette                                      min       rules     model     final     result  latency
child vomiting, lethargic (owner's example)   URGENT    URGENT    URGENT    URGENT    PASS    32.1s
same, hard to wake                            EMERGENCY EMERGENCY EMERGENCY EMERGENCY PASS    17.0s
adult crushing chest pain                     EMERGENCY -         EMERGENCY EMERGENCY PASS    21.3s
infant fever                                  EMERGENCY EMERGENCY EMERGENCY EMERGENCY PASS    24.4s
stroke signs                                  EMERGENCY EMERGENCY EMERGENCY EMERGENCY PASS    16.2s
overdose                                      EMERGENCY EMERGENCY EMERGENCY EMERGENCY PASS    15.2s
suicidal thoughts                             EMERGENCY EMERGENCY EMERGENCY EMERGENCY PASS    11.8s
asthma struggling to breathe                  EMERGENCY -         EMERGENCY EMERGENCY PASS    17.4s
toddler no wet diapers                        EMERGENCY EMERGENCY URGENT    EMERGENCY PASS    48.4s
adult abdominal pain lower right              URGENT    -         URGENT    URGENT    PASS    32.0s
UTI symptoms                                  SOON      -         SOON      SOON      PASS    22.4s
ankle sprain                                  SOON      -         ROUTINE   ROUTINE   MISS    25.7s
two-week cough                                ROUTINE   -         ROUTINE   ROUTINE   PASS    28.8s
mild cold                                     ROUTINE   -         ROUTINE   ROUTINE   PASS    20.0s
prescription refill                           ROUTINE   -         ROUTINE   ROUTINE   PASS    12.5s

Final level at or above the expected minimum: 14/15. Meta alone: 13/15.
```

What it showed:
- **Rules and Meta cover for each other.** Rules missed "pressure in my chest" and "struggling to breathe" (Meta
  caught both); Meta under-called the toddler with no wet diapers (rules caught it). Both rule gaps now have failing
  tests that pass after the fix (commit `d0345e3`).
- **One miss:** the ankle sprain came back ROUTINE against an expected SOON. It's left as a miss rather than
  re-labelled after the fact.
- These vignettes were written for the demo, not by clinicians. This is a smoke test, not clinical validation.

Second run, after the rule fix (same day):

```
vignette                                      min       rules     model     final     result  latency
child vomiting, lethargic (owner's example)   URGENT    URGENT    URGENT    URGENT    PASS    48.5s
same, hard to wake                            EMERGENCY EMERGENCY EMERGENCY EMERGENCY PASS    20.5s
adult crushing chest pain                     EMERGENCY EMERGENCY EMERGENCY EMERGENCY PASS    14.5s
infant fever                                  EMERGENCY EMERGENCY EMERGENCY EMERGENCY PASS    26.9s
stroke signs                                  EMERGENCY EMERGENCY EMERGENCY EMERGENCY PASS    15.6s
overdose                                      EMERGENCY EMERGENCY EMERGENCY EMERGENCY PASS    14.6s
suicidal thoughts                             EMERGENCY EMERGENCY EMERGENCY EMERGENCY PASS    17.4s
asthma struggling to breathe                  EMERGENCY EMERGENCY EMERGENCY EMERGENCY PASS    21.9s
toddler no wet diapers                        EMERGENCY EMERGENCY URGENT    EMERGENCY PASS    28.5s
adult abdominal pain lower right              URGENT    -         URGENT    URGENT    PASS    45.6s
UTI symptoms                                  SOON      -         SOON      SOON      PASS    17.6s
ankle sprain                                  SOON      -         SOON      SOON      PASS    21.6s
two-week cough                                ROUTINE   -         SOON      SOON      PASS    34.0s
mild cold                                     ROUTINE   -         ROUTINE   ROUTINE   PASS    13.9s
prescription refill                           ROUTINE   -         ROUTINE   ROUTINE   PASS    10.9s

Final level at or above the expected minimum: 15/15. Meta alone: 14/15.
```

- Both phrasings the rules missed are now caught by the rules as well as by Meta.
- **Meta's levels vary between runs:** the ankle sprain went ROUTINE → SOON and the two-week cough ROUTINE → SOON
  (over-triage, which still counts as at-or-above the minimum). The ankle-sprain pass is that variation, not a fix.
  Meta's triage latency ranged 11–49 s.

## Backend: `cd backend && .venv/bin/python -m pytest`

Result: **125 passed** (≈131 s). Uses a deterministic test double for the model so tests are fast and offline.

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
| Review fixes | Meta run can't overwrite a concurrent emergency (two sessions); negation stops at clause boundaries; lost background triage recovered by the sweep; patient text can't suggest causes or care level (9 phrasings); overlong model options never shown |
| Duplicate handoffs | 3 requests + direct service call → 1 handoff |
| Workflow transitions | invalid transitions raise; every status has a transition entry |
| Follow-up | overdue handoff → one `ack_reminder` across two agent runs; clinician notified; acknowledging closes it |
| Red-flag rules | the owner's example ≥ URGENT; "can't be woken" → EMERGENCY; 16 vignettes; negation; age bands; question limits; fixed wording has no diagnosis/medication language |
| Triage engine | emergency intake makes no model call; model can't lower the rule level; model can raise it; ungrounded flags dropped; Meta failure → SOON and pages still go out; unsafe acknowledgement replaced by template; level never drops across messages; clinician baseline ignores repeated flags |
| Paging & escalation | urgent pages family doctor + first on-call; routine family doctor only; level rise tightens deadlines; escalation at 15 min once; urgent-care fallback at 30 min once; acknowledged case never escalated; empty care team → fallback immediately; withdrawal stops paging but keeps patient guidance |
| Clinician brief | quotes grounded; "what AI told patient" from the record; versions; attached-report findings in prompt; Meta failure → no brief |
| Thread API | consent confirmation required; dependents; patient view never contains brief/causes/treatment; foreign dependent/thread 404; queue sorted by urgency; unpaged clinician 403; reply → in conversation; clinician urgency change audited; attachment processed without changing thread status; notifications have no medical detail |
| Agent guardrails | messages with medical details blocked (7 cases incl. durations allowed); unknown tools refused; agent that skips the handoff → run FAILED |

## End-to-end: `cd frontend && npx playwright test`

Result: **4 passed against live Meta** (2.7 min, re-run after the review fixes; first run 2.3 min).

- Symptom thread (56 s): parent picks Ava, sends the message → card shows URGENT and Dr. Raman → Meta's tap questions
  appear → parent answers → Dr. Raman opens the thread from the queue, sees the brief with possible causes,
  acknowledges and replies → parent sees the reply as the clinician's and never sees "Possible causes".
- Emergency (1.7 s): "crushing chest pain" → Call 911 screen visible within 1 s of the API response, `tel:911` link.
- The report journey and the isolation test (below) still pass; the journey now creates its report case through the
  API because the upload page was replaced by attachments in threads.

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
| Live eval | Rules missed "pressure in my chest" and "struggling to breathe" | Patterns widened; failing vignettes added first |
| Code review | Background Meta run wrote a stale level/status over a concurrent emergency | Model call first, then row-lock and reload the case before applying; two-session regression test |
| Code review | A "no" in an earlier sentence cancelled a later red flag ("No fever. Can't breathe.") | Negation limited to the same clause |
| Code review | A flag-free thread could sit unleveled if its background run was lost | Scheduler gives it SOON and pages after 90 s |
| Code review | Model acknowledgement could say "sounds like croup" or "go to urgent care" | Triage-specific patient-text filter; violating text is dropped for the template |
| Code review | Model options over 60 characters rendered as buttons the API rejected | Such questions are not asked |
| E2E | Isolation test skipped after re-seed (no unshared case) | Test now creates its own unshared case |
