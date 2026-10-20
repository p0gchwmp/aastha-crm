# Module 4 — verified Patient registration and global UHID

This module extends the existing CRM. Lead, Patient and Appointment identities remain unchanged. Registration never creates a Visit or financial record.

## Reception check after deployment

Use fictional details, not a real person's data.

1. Open an unconverted Lead → Verified Patient registration. Check prefilled name, mobile, gender and approximate age. Opening/cancelling this form creates no Patient/UHID.
2. Correct the details with the person. Enter an actual DOB or approximate age. An approximate age is stored separately with its recorded date; the app does not invent a birthday. Previously recorded estimated DOBs stay marked estimated.
3. Select Registration branch from your permitted branches. Address uses Region → District → Locality. A provisional locality is allowed; invalid hierarchy and rejected/merged localities are blocked by the server.
4. Review possible matches or search explicitly by UHID/name/mobile. Cards show identity details and match reasons. The system never selects a Patient from mobile alone.
5. If it is the same Patient, explicitly Use Existing and confirm Name, Age/Gender and UHID. Linking the Lead creates no new UHID and does not overwrite the existing Patient's demographics. The selected Patient's row version is checked.
6. If it is a genuinely separate Patient, review the matches, tick the separate-Patient confirmation, then verify the registration details. Only the final save creates the Patient/UHID.
7. Retry the same save after a lost response. It must return the original identity. Editing the details after an uncertain response requires searching for the original Patient before saving another registration. Multiple clicks are disabled while saving.
8. Confirm the source Lead becomes Converted once, history remains, DNC remains unchanged and an old outbound follow-up is cleared. Existing source appointments retain the Lead and gain the verified Patient; booking/attendance times are unchanged.
9. Create a new inquiry for this registered Patient and explicitly link it to the same UHID. A Lead can link to only one Patient; one Patient can have many Leads.
10. Search by the shared family mobile: separate family members remain separate. Global Patient/UHID search works across branches within the organization. Registration requires the selected branch permission; another organization's records remain inaccessible.

## Backend safeguards

- Direct registration requires an explicit verification flag and request UUID. A per-user database row lock plus unique registration index makes concurrent identical retries return one identity; a changed payload using the same UUID fails.
- Lead conversion locks and refreshes the Lead, checks its version and selected Patient version, and commits Patient creation, number allocation, Lead link/status/history, audit and appointment identity attachment in one transaction. Retried conversion returns its existing Patient.
- Duplicate hints include name/mobile/DOB plus age/gender/address reasons. Strong mobile/name matches rank ahead of broad recent matches. Matching never merges records.
- Demographic corrections require PATIENT_EDIT, latest row version and a reason. Patient identity is global within the organization; the registration branch is immutable through demographic correction.
- UHID allocation uses one active organization-wide row-locked counter, never resets by financial year and retains database UHID uniqueness. Consultation bill numbering remains separate.

## Migration 0008_patient_registration

Adds nullable Patient retry/hash fields and recorded-age fields, a unique retry index and an active-global-UHID-series index. Consolidates historical UHID counters into one active global counter, preserving old rows inactive, advancing beyond their maximum, and preserving all existing Patient IDs/UHIDs. The bootstrap uses this same global counter instead of creating a new annual UHID series. Rollback does not reverse the counter consolidation or reset numbering.

Before rollout, take a fresh durable backup of the current staging database under frozen project rule 138. Deploy API/migration first, verify readiness, then deploy the web image on the same commit. Never restore the clinic database just to test a backup; restore into an isolated database.

## Validation

CI exercises HTTP registration, shared-mobile matching, explicit existing/new decisions, branch/organization boundaries, stale updates and audits. PostgreSQL tests include two concurrent conversions of one Lead, identical direct registration retries, and simultaneous cross-branch unique UHIDs. A populated migration fixture preserves Patient IDs/UHIDs across upgrade and consolidates conflicting annual counters; logical backup/restore compares Patient, Lead links, contact/address, counters, appointment/history and audit records. Chromium exercises verified conversion, existing-Patient linking and separate-family registration, plus the previous Staff/Lead/Appointment workflows.

Automated CI runs in an isolated environment. User acceptance in the deployed signed-in clinic remains a separate final check.
