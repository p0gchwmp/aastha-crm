# Aastha CRM

Future-proof Phase 1 CRM for Aastha Skin & Dermato-Cosmetic Centre.

## Stack
- PostgreSQL 16
- FastAPI + SQLAlchemy 2 + Alembic
- Next.js + TypeScript
- Docker Compose

## Implemented Phase 1
- Reception dashboard and role-based login
- Lead Register, follow-ups, previous inquiries, Lost→Reopen, DNC
- Appointment scheduling and overlap protection
- Lead→Patient conversion with shared-mobile safety
- Global UHID and Patient Register
- Visit Register and Patient identity confirmation
- Locality + Chief Complaint non-blocking maker-checker
- Consultation Finance with 10-day per-patient rule
- Atomic sequential consultation bill numbering
- Cash/UPI/Card/Other payment collection
- Doctor Complimentary action
- Focused Finance audit/corrections
- Printable consultation bill and receipt
- Legacy Patient CSV/XLSX staging + duplicate review + import
- Hard firewall against historical financial migration
- Third-party/AI integration architecture and DNC boundaries
- Procedure Order + Procedure Execution clinic workflow
- Pay-first external Procedure Finance clearance bridge
- Tenant-scoped Finance/Inventory integration clients + transactional outbox/inbox
- Rendering-branch Inventory completion events with no Patient identity

## Quick start
1. Copy `.env.example` to `.env`.
2. Run `docker compose up --build`.
3. Compose runs Alembic migrations and development seed.
4. Web: http://localhost:3000
5. API docs: http://localhost:8000/docs

### Development logins
- Reception: `reception` / `Reception123!`
- Super Reception: `superreception` / `SuperReception123!`
- Admin: `clinicadmin` / `ClinicAdmin123!`
- Super Admin: `admin` / `ChangeMe123!`
- Doctor: `doctor` / `Doctor123!`

**Change all seeded passwords before any real deployment.**

## Validation
- Backend tests: **42/42 passing**
- OpenAPI: **70 paths**
- PostgreSQL DDL compile: **63 mapped tables**
- Frontend parser syntax: **17 TS/TSX files, 0 syntax errors**

## UAT
See `docs/UAT_PHASE1.md` and `docs/legacy_patient_import_template.csv`.

## Frozen architectural rules
- Clinical and Finance remain separate domains.
- Lead, Patient, Appointment, Visit, Procedure Order and Procedure Execution are stable operational backbone entities.
- External systems use authenticated/versioned APIs, never direct DB writes.
- Mobile is never unique for Patient identity.
- Appointment booking never creates UHID.
- Lead conversion is idempotent and duplicate-aware.
- Final business numbers are allocated atomically and protected by UNIQUE constraints.
- DNC is enforced server-side at every outbound boundary.
- Legacy financial data is never imported.
- Future Procedure Finance/Inventory attach via stable IDs/API/events without replacing the CRM backbone.


## Procedure Finance / Inventory development bridge
See `docs/PROCEDURE_FINANCE_INVENTORY_API.md`.

With the API running, sandbox external systems can be simulated with:
```bash
python tools/procedure_finance_sandbox.py
python tools/inventory_sandbox.py
```
Development integration keys are intentionally non-production and must be rotated before deployment.

## Production deployment candidate

This revision adds deployment/UAT hardening. Read `docs/PRODUCTION_DEPLOYMENT_UAT_RUNBOOK.md` before deployment.

### Production quick start

```bash
cp .env.production.example .env.production
chmod 600 .env.production
# Replace all placeholders, including one-time BOOTSTRAP_* passwords.
python scripts/preflight.py --env-file .env.production --require-bootstrap
ENV_FILE=.env.production scripts/deploy.sh
python scripts/smoke_uat.py --base-url http://127.0.0.1:8080 --username reception --password '<assigned-password>'
```

Production differs from development deliberately:
- PostgreSQL is internal-only.
- API/web are exposed only through the Nginx gateway.
- API docs are disabled by default.
- no hard-coded development user passwords are used in production;
- database migrations and production bootstrap are one-shot services;
- existing CRM databases are backed up before migration by `scripts/deploy.sh`;
- DNC, branch and role-validity checks remain server-side;
- first-run users can rotate passwords at **My Password**.

For backup and recovery:
```bash
ENV_FILE=.env.production scripts/backup.sh
ENV_FILE=.env.production scripts/verify_restore.sh backups/<dump>.dump
```

**Important:** the included gateway listens on HTTP 8080. Use HTTPS/TLS or a trusted private network/VPN before any remote clinic access.
