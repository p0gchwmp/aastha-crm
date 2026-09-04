# Implementation status

## Milestone 1 — Reception vertical slice
Implemented secure login, role/permission context, Lead Register, previous inquiries, follow-up history, Lost/No-show reopening, DNC outbound enforcement, doctor/branch appointment availability, overlap protection, and Reception web workflow. Appointment booking never creates UHID.

## Milestone 2 — Lead → Patient → UHID → Visit
Implemented shared-mobile-safe matching, duplicate suggestions, Use Existing vs Create Separate, serialized/idempotent Lead conversion, global UHID generation after verified registration, Patient search/detail/history, identity confirmation before Visit creation, Visit Register, appointment-to-Patient linking, and Chief Complaint linkage.

## Milestone 3 — Consultation Finance
Implemented effective-dated fees, patient-level 10-day eligibility, safe entitlement consumption, consultation bill/payment separation, atomic sequential bill numbering, payment modes/partial payments, full-payment clearance + entitlement creation, Doctor Complimentary action, Admin corrections, focused audit, and India-local-date reports.

## Milestone 4 — Operational hardening
Implemented:
- Non-blocking Locality maker-checker: Reception proposes; Super Reception/Admin approve/correct/merge/reject where safe.
- Non-blocking Chief Complaint maker-checker with canonical merge of existing Visit links.
- Referenced pending masters cannot be rejected without correction/merge.
- Legacy Patient CSV/XLSX upload → safe-field staging → duplicate review → commit.
- Legacy financial columns are stripped before staging and never imported.
- Import batches are organization-scoped and audited.
- Admin-only legacy import permission.
- Admin audit viewer API/UI and financial change-request queue.
- Printable consultation bill and payment receipt browser documents.
- Development logins expanded for Super Reception and Admin UAT.
- Phase 1 UAT checklist and legacy import template included under `/docs`.

## Validation performed
- Python bytecode compilation: PASS.
- Backend unit/architecture/business-rule tests: **31/31 PASS**.
- FastAPI OpenAPI generation: PASS — **56 API paths**.
- PostgreSQL SQLAlchemy DDL compilation: PASS — **63 mapped tables** / 68 DDL statements.
- Frontend TS/TSX parser syntax validation: PASS — 16 files, 0 syntax errors.

## Environment limitation
- Docker/PostgreSQL binaries are not available in this execution environment, so a full live PostgreSQL/Docker integration/UAT run could not be executed here.
- React/Next packages are not installed locally in this execution environment, so a real `next build` remains a development-machine validation step.

## Next milestone
1. Live Docker/PostgreSQL UAT and bug-fix pass.
2. Procedure Order / Procedure Execution clinic workflow UI.
3. External Procedure Finance + Inventory API contract and sandbox adapter.
4. WhatsApp/Voice AI integration adapter after appointment APIs pass live UAT.


## Milestone 5 — Procedure Finance + Inventory integration bridge
Implemented:
- Doctor-only Procedure Order creation while Reception retains read-only operational visibility.
- Procedure Order and Procedure Execution/session remain separate.
- Procedure Finance remains external; CRM stores only a financial-clearance projection.
- Pay-first enforcement: sessions require `CLEARED` or `COMPLIMENTARY`.
- Every performed session requires an actual Procedure Visit for the same Patient.
- Rendering Branch must match the Procedure Visit branch.
- Procedure session start/completion synchronizes the linked Visit status.
- Session completion emits a tenant-scoped `PROCEDURE_COMPLETED` Inventory event.
- Inventory event intentionally excludes Patient name/UHID/clinical notes.
- One completed session marks the order `PARTIALLY_COMPLETED`; explicit Doctor close supports future multi-session packages.
- Pre-treatment cancellation emits a Procedure Finance cancellation event and is blocked after any completed session.
- Organization-scoped external integration clients with hashed API credentials and explicit scopes.
- Procedure Finance order/cancellation event feed + acknowledgement endpoints.
- External financial-status callback with atomic PostgreSQL inbox idempotency.
- Finance callbacks cannot overwrite `PARTIALLY_COMPLETED`/`COMPLETED` clinical history.
- Inventory completion event feed + idempotent acknowledgement behavior.
- Development Finance and Inventory sandbox adapters under `/tools`.

## Current validation
- Backend tests: **42/42 PASS**.
- Python compilation: PASS.
- FastAPI OpenAPI generation: PASS.
- PostgreSQL SQLAlchemy DDL compilation: PASS — **63 mapped tables / 68 create-table DDL statements**.
- Alembic migrations compile through `0005_procedure_integration_clients`.
- Live Docker/PostgreSQL + real Next.js production build still requires a development machine with Docker and installed frontend dependencies.
