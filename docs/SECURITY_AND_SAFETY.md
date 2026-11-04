# Security, Privacy and Clinical Safety

**Status: prototype.** CareBridge hasn't had a privacy impact assessment, threat
risk assessment, or clinical safety review, and isn't approved to process real personal health information (PHI).
Using it with real PHI in Canada would need, at minimum, a PIPEDA/PHIPA-aligned privacy program, Canadian data
residency (`ca-central-1`), a signed agreement with the model provider covering PHI, and a Health Canada SaMD
classification review.

## Clinical safety controls

| Risk | Control | Where |
|---|---|---|
| Invented or altered results | Every extracted value, unit, range and flag must appear verbatim in the cited source line; cross-checked against a deterministic parser; mismatches marked `NEEDS_REVIEW` and surfaced to patient and clinician | `agent/validation.py::reconcile_findings` |
| Model infers abnormality | Prompt forbids inferring flags; out-of-range is computed deterministically from the printed interval | `outside_range` |
| Diagnosis, prescribing, false reassurance, triage (report explanations) | Regex safety lint on every generated sentence; fails → regenerate once → `NEEDS_CORRECTION` | `UNSAFE_PATTERNS` |
| Numbers not in the report | Any number in generated text must appear in the findings or report date | `number_issues` |
| Patient and clinician views disagree | Every result the clinician summary calls out must also be flagged to the patient; summary values must equal stored findings | `validate_outputs` |
| Concerning findings missed | Every flagged / out-of-range / unverified finding must appear in the patient's "discuss with a clinician" list and the clinician key findings | `validate_outputs` |
| Unvalidated output reaches anyone | Only `ACTIVE`/`CORRECTED` summaries are shown or shared; `FAILED_VALIDATION` blocks consent | `services.active_summary` |
| Model score read as clinical probability | No confidence scores are shown; findings show "Matches report" (verbatim check) or "Needs review" | UI |
| Automation replaces clinician | AI output is labeled as a draft; clinician must mark it Accurate / Needs correction / Reject before completing review; referrals are only *prepared* as admin tasks | `services.complete_review` |
| Medical details in notifications | Agent messages pass an administrative-only filter (no numbers, no test names) | `admin_message_issues` |
| No guarantees implied | Consent page says no response time is guaranteed; the symptom composer says to call 911 in an emergency | consent page, composer |

## Symptom triage controls

| Risk | Control | Where |
|---|---|---|
| Emergency instruction delayed by the model | Red-flag rules run synchronously on every message before any model call; an EMERGENCY result returns with the 911 message in the same response, and the UI shows a full-screen Call 911 screen | `triage/rules.py`, `engine.intake` |
| Model under-triages | Final level = max(rule level, Meta level); the thread's level only goes up unless a clinician changes it | `engine._raise_level` |
| Model invents symptoms | Every red-flag quote from Meta must appear verbatim in the patient's messages; ungrounded flags are dropped and recorded | `triage/grounding.py` |
| Model tells the patient where to seek care | Care-level wording comes only from fixed templates; Meta's free text (a short acknowledgement) passes the safety lint and invented-number check, is regenerated once, then dropped | `triage/content.py`, `patient_text_issues` |
| Patient sees a diagnosis or treatment | Possible causes and the treatment draft live only in the clinician brief; the patient serializer never includes them (tested) | `serializers.patient_thread` |
| Nobody responds | Deterministic paging: family doctor, then on-call by priority; URGENT pages must be acknowledged in 15 min or the next clinician is paged; after 30 min, or if nobody is on call, the patient is told to go to urgent care or an emergency department | `triage/routing.py`, scheduler |
| Meta unavailable | Rule level stands, otherwise SOON; pages still go out; patient sees the template guidance | `engine._run_model_triage` |
| A clinician's judgment overridden | After a clinician sets the level, only new rule red flags can raise it; the model's view is recorded only | `engine`, `urgency_baseline_flags` |
| Consent withdrawn mid-emergency | Clinician access and escalation stop; the patient's 911 screen and urgent-care advice stay | `services.withdraw_consent` |

The red-flag phrases, question bank and template wording were written for a demo and must be reviewed
by clinicians before any real use. The live evaluation (`python -m app.triage.eval`) is a smoke test on synthetic
vignettes, not clinical validation.

The safety lint is a backstop, not proof of safety: it catches common phrasings and won't catch every unsafe
paraphrase. Clinician review is the real control.

## Consent

- Symptom threads use care-team consent: before the first send the composer states that the conversation and
  attachments go to the family doctor and on-call clinicians; sending is the confirmation (`consent_confirmed: true`
  is required by the API). Each paged clinician gets their own handoff on that consent, and access still requires it
  to be `GRANTED`.
- Consent is enforced in the backend, not the UI. `create_handoff` re-reads active consent inside the request, and
  clinician access (`access.clinician_case`) requires a non-cancelled handoff backed by consent that's still `GRANTED`.
- Before consenting, the patient sees the recipient, what's shared (report, findings, AI clinician summary), and the purpose.
  Explicit `confirmed: true` is required. Timestamp, scope, purpose and recipient are stored and audited.
- Withdrawal cancels open handoffs and tasks and removes future clinician access immediately. The UI states that
  withdrawal can't undo access that has already happened.
- One handoff per consent (DB unique constraint + idempotent service). Duplicate requests can't create duplicate referrals.

## Authentication and authorization

- bcrypt password hashes; HS256 JWT (12 h) in an `httpOnly`, `SameSite=Lax` cookie (`Secure` in production) or
  a Bearer header. Logout bumps `token_version`, which invalidates every issued token.
- Roles: PATIENT, CLINICIAN, ADMIN, enforced per route. Record access is checked in `app/access.py`:
  - patients see only their own cases (other patients' cases return 404, so existence isn't revealed);
  - clinicians see only cases with an active consented handoff addressed to them;
  - admins have no route to report contents, findings or summaries. Admin views carry workflow metadata,
    audit events and model telemetry only. Agent tool results are stripped from admin execution views.
- Clinical notes are visible to the clinician only; the patient sees the next step and the clinician's message.

## Audit

`audit_events` records actor (user/agent/system), action, resource and metadata for logins, uploads, AI
processing, summary generation, consent granted/withdrawn, handoff sent, clinician case/document views,
acknowledgment, review start/assessment/completion, follow-up tasks, notifications and status changes.
Details carry ids, counts and statuses, never result values or report text.

## Input handling

- PDF uploads: magic-byte check, 10 MB limit, stored under random keys, path-traversal-safe loader, served with
  `Cache-Control: no-store`.
- All request bodies validated by Pydantic DTOs with length limits; client forms mirror them with Zod.
- Model tool arguments are parsed and validated per tool. Unknown tools are refused.

## Secrets

- `MODEL_API_KEY`, `JWT_SECRET` and DB credentials come from `.env` (gitignored, `chmod 600`). In AWS, inject them from
  Secrets Manager or SSM Parameter Store. Keys are never logged; logs record model id, latency and token counts only.

## Known gaps before real-world use

- Local disk document storage. Production needs a private, SSE-KMS encrypted S3 bucket in `ca-central-1` with presigned reads.
- No MFA, password reset, account lockout, or rate limiting.
- In-process background tasks. A durable queue is needed for restarts mid-run.
- No field-level encryption, retention policy, or automated backups configured.
- Safety lint is English-only and pattern-based.
