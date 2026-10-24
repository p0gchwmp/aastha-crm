# Module 8 — Doctor and Clinical Assistant Management

Deployment candidate. A fresh downloaded backup is required before live deployment/migration. No live clinical accounts or Patient records are created by the test suite.

## Account setup

1. Admin opens Clinical Team and creates two Doctors with distinct codes/usernames and appropriate allowed branches. Existing operational Doctor profiles can receive a login without changing their Doctor ID; do not create a duplicate profile for an existing Doctor.
2. Create a Clinical Assistant with branch access. Share temporary credentials securely outside chat. Each person changes their temporary password at first login.
3. Open Doctor schedules (existing schedule-management screen), choose the new Doctor, and set branch/timing/effective dates. New schedules and booking/Visit assignment are rejected outside the Doctor's authorized branches.
4. Verify a password reset ends old sessions; reset credentials must be changed. Deactivation disables login and future Doctor selection without deleting existing appointments, Visits, notes or payments. Existing operational work is retained and must be managed explicitly.
5. Doctor/Assistant account types are fixed. Reception accounts stay on the separate Staff Users screen. Accounts carrying privileged/mixed roles are not editable through this module.

## Preparation and handover

1. Reception creates a clearly labelled fictional Patient/Consultation Visit assigned to Doctor A.
2. Admin or Doctor A opens Assistant Assignments and assigns an active Assistant with access to that Visit's branch. Doctor B cannot assign or open Doctor A's consultation. Assignment/reassignment invalidates stale Doctor Visit screens.
3. Assistant signs in and sees only assigned Visits. Confirm Name, Age/Gender and UHID. Record history/presenting concerns, allergy status, reported current medicines, observations and measured vitals. Unmeasured values stay blank; unknown allergies are not treated as none reported.
4. Save Draft, reload and reopen. Confirm values remain. Submit to Doctor; submitted preparation becomes read-only. This does not start/complete the Visit, create diagnosis/prescription, book a follow-up, or change money/UHID.
5. Doctor A opens the consultation, sees preparation separately from Doctor notes, and starts the consultation after identity confirmation. Completion is rejected until assigned preparation is submitted and reviewed.
6. Doctor may return submitted preparation with a reason. Assistant sees the reason, corrects the preserved draft and resubmits. Earlier versions remain visible only to the authorized Doctor.
7. Doctor marks the current preparation Reviewed, records their own consultation and completes. Doctor identity/time/version of review are stored. Assistant cannot alter reviewed preparation or read the Doctor's private assessment/plan.
8. Reception sees COMPLETED in Visits and Patient history without Assistant clinical content. The second Doctor and an unassigned Assistant cannot open this preparation through API URLs.
9. Two screens: save on one, attempt an old save on the other. It must be rejected. Retry of the same unchanged request must not create another revision. Retrying an unchanged review remains safe.
10. Reassignment before review removes the previous Assistant's access and starts a blank current preparation for the new Assistant; previous saved content is retained in protected revision history. Reviewed preparation is immutable.

## Upgrade verification

CI runs the existing clinic workflows, populated additive 0012 upgrade comparison (including Doctor notes), PostgreSQL concurrent Assistant saves, complete-row logical backup/restore including preparations/revisions, production web/Docker builds and a Chromium Admin → Assistant → Doctor workflow. Live user acceptance remains separate.

The module does not add diagnosis/medicine masters, prescribing, investigations, Procedure Finance or inventory. Existing Doctor consultation behavior remains available when no Assistant is assigned.
