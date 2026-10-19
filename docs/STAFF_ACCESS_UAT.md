# Module 1: Reception Staff Access

The Phase 1 CRM repository is `p0gchwmp/aastha-crm`. This module is for that application only.

## Scope

Admin and Super Admin can open **Staff Users** to create Receptionist and Super Receptionist accounts, assign one or more clinic branches, edit access, deactivate/reactivate accounts, and reset temporary passwords. Doctor and privileged account administration is outside this module.

Each staff member receives their own username. Temporary passwords must be replaced at first login. Deactivation, reassignment, password reset and password change invalidate previous login tokens. Clinic records are preserved. Staff changes and password changes are audited without passwords or hashes.

## Acceptance checks (fictional accounts only)

1. Sign in as Admin. Staff Users is visible on desktop and mobile.
2. Create a Receptionist with a unique username and Paloura branch access.
3. Sign in in a separate browser profile. Only My Password is usable until the temporary password is changed.
4. Change the password, then sign in again. Confirm assigned branch access.
5. Confirm Receptionist and Doctor accounts cannot list, create, edit or reset staff through the API.
6. Change the account to Super Receptionist and Amphalla. The old session is rejected; the new session has only the new branch access.
7. Reset the password. Old passwords and tokens fail, and the replacement password must be changed.
8. Deactivate the account. Both login and existing tokens fail. Reactivate it and verify a fresh login is required.
9. Review Admin Audit for the changes. No passwords or password hashes appear.
10. A stale Admin edit must fail with a refresh message. Duplicate usernames (including case variants), other-clinic branches and attempts to modify privileged users must fail.

## Deployment

Migration `0006_staff_access` adds two authentication columns, a case-insensitive unique login index, and the Staff Manage permission for Admin/Super Admin. Existing users retain their passwords. The migration intentionally refuses ambiguous duplicate usernames instead of changing identities automatically.

Take and verify a current database backup before deployment. Run CI PostgreSQL migration and account lifecycle tests, including upgrade of a populated pre-staff schema. Deploy API first; verify readiness; then deploy the frontend and run this checklist. The other CRM repositories and deployments are outside this release.

A passed automated browser test does not replace staff acceptance on the deployed environment. Full clinic go-live still requires the remaining workflow UAT and a proven restore.
