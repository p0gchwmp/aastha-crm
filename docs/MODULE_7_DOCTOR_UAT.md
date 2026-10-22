# Module 7 — Doctor Consultation UAT

Candidate only until deployed and accepted by the clinic. Download a fresh database backup before the additive 0011 migration and deployment.

1. Reception: create a Consultation Visit for a fictional verified Patient, assigned to the Doctor's linked profile. Keep the UHID.
2. Doctor login: open Doctor Consultations, choose today's India date, and find that Patient. An unassigned Visit or another Doctor's Visit must not be available.
3. Open the Visit. Confirm Name, Age/Gender and UHID with the Patient, then Start Consultation. Reception's Visit Register should show IN PROGRESS.
4. Enter History, Examination, Assessment, Treatment plan, Follow-up advice and an optional Follow-up date. Save Notes, refresh, and confirm the text and date remain.
5. Open the same Visit in a second tab. Save a change in the first tab, then try saving the older second tab. The stale save must be rejected; copy unsaved text before refreshing.
6. Complete Consultation and accept the completion prompt. The Visit should become COMPLETED with a completion timestamp. Notes become read-only, and Saved versions retains earlier values.
7. Reception: confirm COMPLETED appears in Visits and Patient history. Clinical text and Doctor Consultations must not be accessible with Reception credentials.
8. Create a later Visit for the same Patient and Doctor. The Doctor should see the prior consultation in Patient history, within permitted branches.
9. Check the existing consultation Bill/Receipt still works. This module does not change payment, entitlement, appointment, UHID or Procedure execution rules.

Saved-note versions are append-only through application APIs. Follow-up date/advice does not book an appointment or trigger outbound contact. Procedure Visits continue through Procedure Sessions. Completed-note corrections are outside this module; no silent editing or reopening.

Automated evidence: API privacy/transition/retry/rollback tests, PostgreSQL concurrent saves and populated upgrade comparison, full-content backup/restore including notes and revisions, production Next.js and Docker builds, Chromium start/save/interrupted-save retry/completion/history workflow. Clinic UAT acceptance is recorded separately after actual deployment.
