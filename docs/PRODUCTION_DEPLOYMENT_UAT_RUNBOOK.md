# AASTHA CRM — Production Deployment & UAT Runbook

## Status
This repository is a deployment candidate. The automated backend/architecture suite passes in the build environment, but the complete Docker + PostgreSQL + browser stack must be run on the target development/production host before clinic go-live.

## Production topology
Internet/LAN user → HTTPS/TLS terminator → `gateway` (Nginx) → Next.js web + FastAPI → internal PostgreSQL.

- PostgreSQL has no host port in `docker-compose.prod.yml`.
- API and web are not published directly; only the gateway is exposed.
- `/api/v1/auth/login` is rate-limited at Nginx.
- Production API documentation is disabled by default.
- Database readiness is checked at `/health/ready`.
- The gateway in this repository listens on HTTP port 8080. **Do not expose it to the public internet without HTTPS/TLS in front of it.** Use a trusted reverse proxy/load balancer/Caddy/Cloudflare Tunnel/VPN according to the clinic's hosting decision.

## 1. Host prerequisites
- Linux server/VM recommended.
- Docker Engine + Docker Compose plugin.
- Persistent disk with monitored free space.
- Encrypted disk/storage recommended because backups contain patient information.
- Restricted administrator SSH access.
- DNS + TLS certificate before internet exposure.

## 2. Prepare secrets
```bash
cp .env.production.example .env.production
chmod 600 .env.production
```
Replace all placeholders. Use unique passwords for database, JWT secret, Super Admin, Admin, Reception, Super Reception and Doctor.

The `BOOTSTRAP_*` passwords are required for the first deployment only. The bootstrap is idempotent and does not reset existing users. After first successful login/password rotation, the bootstrap password variables may be removed from `.env.production`.

## 3. Preflight
```bash
python scripts/preflight.py --env-file .env.production --require-bootstrap
```
Must report `Preflight PASSED` on a fresh installation.

## 4. First deployment
```bash
ENV_FILE=.env.production scripts/deploy.sh
```
The deployment script:
1. validates configuration;
2. builds production images;
3. starts PostgreSQL;
4. detects fresh vs existing CRM database;
5. takes a verified pre-migration backup when upgrading an existing database;
6. runs Alembic migrations in a one-shot `migrate` container;
7. runs idempotent production bootstrap in a one-shot `bootstrap` container;
8. starts API/web/gateway.

## 5. Health check
```bash
python scripts/smoke_uat.py --base-url http://127.0.0.1:8080 \
  --username reception --password '<assigned-password>'
```
Expected:
- PASS liveness
- PASS database readiness
- PASS authentication
- PASS identity/roles

## 6. First-login security
Every assigned user should open **My Password** and change the initial password. Do not reuse the same password across clinic users.

Emergency server-side reset (only from the trusted server/admin console):
```bash
docker compose --env-file .env.production -f docker-compose.prod.yml exec -T \
  -e NEW_PASSWORD='<new-strong-password>' api \
  python -m app.manage_user_password --username reception
```
The tool never prints the password.

## 7. Backup
```bash
ENV_FILE=.env.production scripts/backup.sh
```
The script creates a PostgreSQL custom-format backup with restricted file permissions and verifies its catalog.

Keep backups on protected/encrypted storage and copy them off the application host according to clinic retention policy.

## 8. Non-destructive restore drill
```bash
ENV_FILE=.env.production scripts/verify_restore.sh backups/aastha_YYYYMMDDTHHMMSSZ.dump
```
This restores the dump into a temporary database, checks the CRM organization and Alembic version, then deletes the temporary database. Run a restore drill before go-live and periodically thereafter.

## 9. Emergency live restore
Only after confirming a current backup and taking the application out of service:
```bash
CONFIRM_RESTORE=YES_RESTORE_AASTHA ENV_FILE=.env.production \
  scripts/restore.sh backups/<confirmed-dump>.dump
```
After restore, run smoke/UAT before reopening staff access.

# Mandatory Clinic UAT

## A. Authentication / roles
- Receptionist can log in and sees Reception-authorized functions.
- Receptionist cannot access bulk export/Admin-only functions.
- Super Reception can resolve maker-checker items but has no bulk export.
- Admin can manage approved finance corrections/imports/reports.
- Doctor can perform clinical/complimentary/procedure actions but not normal cashier actions.
- Expired `UserRole` assignments do not grant permissions.
- Branch-restricted users are blocked from appointment/visit/consultation-finance actions in unauthorized branches.

## B. Lead Register
- Create Lead with mandatory Lead Source.
- Search by name/mobile.
- Previous inquiries display.
- Genuine new inquiry is not blocked by previous Lead.
- Lost/No-show Lead can reopen using same Lead ID.
- DNC blocks outbound/third-party calling assignment and marketing export.
- DNC Lead may still contact clinic inbound.
- Lead interaction/status history remains intact.

## C. Appointment
- Lead appointment does not create UHID.
- Availability follows Doctor schedule + exceptions.
- Overlapping Doctor appointment is rejected.
- Appointment changes to booked/check-in states correctly.
- Unauthorized branch booking is rejected.

## D. Patient / UHID
- Convert Lead through prefilled registration.
- Conversion is idempotent.
- Same mobile may belong to multiple family members.
- Possible duplicate is suggested, never auto-merged.
- Global UHID generated only after confirmed registration.
- Patient identity confirmation is required before Visit creation.

## E. Visits / maker-checker
- Consultation, Procedure, Report Check, Follow-Up and Other Visit types work.
- Custom Locality does not block registration and enters maker-checker queue.
- Custom Chief Complaint does not block Visit and enters maker-checker queue.
- Checker can approve/correct/merge/reject as designed.

## F. Consultation Finance
- Fee resolution selects correct effective Doctor/Branch fee.
- 10-day entitlement is per Patient, not complaint.
- One free follow-up can be consumed only once.
- Two simultaneous attempts cannot double-consume entitlement.
- Consultation bill number allocation is atomic and unique.
- Cash/UPI/Card/Other payment works.
- Overpayment is rejected.
- Full payment creates clearance + follow-up entitlement.
- Doctor complimentary requires Doctor login.
- Finalized payment-mode correction requires authorized Finance role and audit reason.
- Paid bill cannot be silently deleted/voided through an unsupported refund path.
- Restricted user cannot bill/pay in another branch.

## G. Legacy import
- CSV and XLSX stage correctly.
- Incomplete profile imports as `LEGACY_INCOMPLETE`.
- Duplicate candidates are shown.
- Old financial columns never enter Patient migration data.

## H. Procedure bridge
- Doctor creates Procedure Order.
- External Finance status `PAYMENT_PENDING/HOLD` blocks execution.
- `CLEARED` or `COMPLIMENTARY` permits execution.
- Execution must belong to a real Procedure Visit.
- Starting execution updates Visit to `IN_PROGRESS`.
- Completing execution updates Visit to `COMPLETED`.
- One session completion does not close a multi-session order.
- Inventory event occurs only after Procedure Execution completion.
- Inventory event uses Rendering Branch and does not include patient identity.

## I. Third-party/API boundaries
- Third-party credentials see only authorized scopes.
- External API retries do not create duplicates (idempotency).
- DNC cannot be bypassed through export/assignment/API.
- External Procedure Finance cannot directly write CRM database tables.

## J. Concurrency
Using two browser sessions/users, test simultaneously:
- bill number finalization;
- free-follow-up consumption;
- stale Lead update;
- stale Patient update;
- overlapping appointment creation.
Expected: no duplicate number, no double entitlement use, stale writes rejected.

## K. Backup/restore
- Create backup.
- Verify backup catalog.
- Run `verify_restore.sh` successfully.
- Record the date and operator of the restore drill.

# Go-live gate
Do not go live until all of the following are true:
- automated backend tests pass;
- production Docker build succeeds;
- migrations complete on a fresh test DB;
- smoke test passes;
- manual UAT sections A–K are signed off;
- restore drill passes;
- HTTPS is active for any non-local access;
- production passwords have been changed from initial bootstrap values;
- off-host/encrypted backup plan is active;
- clinic confirms the exact Consultation Bill numbering format with its accounting/CA requirements.
