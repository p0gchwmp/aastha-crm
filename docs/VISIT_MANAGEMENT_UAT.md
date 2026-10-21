# Module 5 — Visit Management

Patient registration was accepted by the clinic before this milestone. This module adds a verified encounter under an existing Patient. One permanent UHID can have many Visit IDs.

## Reception workflow

1. Patients → search UHID, name or mobile → explicitly open the correct person. A shared mobile may show several family members.
2. Select **+ New Visit**. The form reloads the Patient details; verify Name, Age/Gender and UHID with the person and tick the confirmation.
3. Choose walk-in or explicitly select today's appointment. An appointment must already belong to the verified Patient. The linked branch and doctor are fixed to that appointment.
4. Choose branch, doctor (or unassigned), Visit type, and optional multiple chief complaints. Search the complaint master; **+ Propose complaint** permits immediate use while maker-checker review is pending. Report Check does not require a reason.
5. Select **Create Visit**. The confirmation includes Visit ID and unchanged UHID. The new Visit starts Waiting. Check-in time comes from the server and displays in Asia/Kolkata.
6. Patient history shows the latest 50 Visits in the user's allowed branches. Open a Visit for details. The Visit Register supports date, branch, doctor, type and status filters and pages of 50.

Appointment attendance remains separate: this action does not rewind Completed attendance or finish a medical consultation. Clinical status progression and consultation finance are subsequent workflow work.

## Clinic acceptance checks after deployment

- Reception: create one fictional consultation, verify same UHID and new Visit ID in history and today's register.
- Create a Report Check without a complaint/reason and verify a different Visit ID under the same UHID.
- Shared-mobile family: ensure the selected person's displayed Name/Age/Gender/UHID is correct.
- Appointment: select a registered Patient's appointment today, confirm matching branch/doctor; a second Visit for that appointment is rejected. A completed attendance can be linked without changing its status.
- Concurrent/stale screen: change Patient details in another session, then submit old Visit form. Expect rejection and reopen for verification.
- Reception branch restrictions: cannot create/read Visit in an unauthorized branch, including through Patient history.
- Admin: see allowed branch records and VISIT_CREATED audit with actor/time/verification evidence.
- Doctor: read allowed Visit history; Visit creation remains permission-controlled.
- If save response is interrupted, retry the unchanged form. It returns the saved Visit ID. Before closing/reopening, check Patient history to avoid a new intentional request.

## Engineering validation and deployment

Migration `0009_visit_management` adds nullable retry and verification fields and indexes; existing Patient IDs, UHIDs, Visits and complaint links are retained. Historical rows are not falsely marked identity-verified.

CI covers SQLite HTTP regressions, PostgreSQL row-lock races, blank/populated migrations, full-content logical backup/restore including Visits, Chromium Reception workflow, web build and Docker image builds. Results are recorded in the PR; clinic acceptance is separate.

Before Render deployment, download a fresh database backup (frozen architecture rule 138). API must deploy first to run the additive migration, then web. Canonical services only: aastha-phase1-api-staging and aastha-phase1-web-staging. Keep auto-deploy off. Do not deploy an old API that writes Visits without the new verification/retry contract.
