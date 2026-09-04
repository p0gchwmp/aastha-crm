# AASTHA CRM — Deployment Candidate Validation Report

## Automated checks completed in build environment
- Backend pytest: **50/50 passed**.
- Python source/migration/script compile: passed.
- Alembic migration chain: single head at `0005_procedure_integration_clients`.
- PostgreSQL DDL generation: **63 mapped tables compile**.
- FastAPI OpenAPI: **73 API paths** in development configuration.
- Health endpoints present: `/health`, `/health/live`, `/health/ready`.
- Production configuration validator rejects default JWT secret and wildcard CORS.
- Production Compose static tests confirm PostgreSQL is not published to host.
- Development passwords removed from browser login defaults.
- Role validity dates enforced when resolving permissions.
- Branch access enforcement wired at appointment, Visit and consultation-finance boundaries.
- Direct consultation bill payload is checked against Visit patient/doctor/branch.
- Deployment preflight passes with strong sample configuration.
- Shell deployment/backup/restore scripts pass shell syntax checks.
- TypeScript/TSX parser-level check found no syntax/parser errors after latest UI change.

## Environment limitations
The execution environment used to prepare this candidate does **not** provide Docker, so the following could not be executed here:
- real PostgreSQL container startup;
- Alembic against a live PostgreSQL instance;
- full Next.js production build (npm dependencies are not installed and external npm fetch is unavailable here);
- browser end-to-end UAT;
- real backup/restore commands inside PostgreSQL containers.

These are mandatory on the target Docker development host before clinic go-live. Follow `PRODUCTION_DEPLOYMENT_UAT_RUNBOOK.md`.

## Go-live classification
**Deployment candidate / UAT required — not yet certified for live clinic use.**
