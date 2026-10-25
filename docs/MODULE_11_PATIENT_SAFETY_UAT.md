# Module 11 — patient safety information and medication reconciliation

Stage 1 of the approved adult/child prescription-support design. This release records observations only. It does not calculate doses, check interactions, map ingredients automatically, or declare medicines safe. Clinical rule publishing and two-reviewer approval remain later stages.

## Behaviour

- Assigned Clinical Assistants can prepare a structured safety record for an open assigned Visit until preparation submission. Assigned active Doctors can edit and confirm review during an in-progress consultation.
- Allergies, medicines and medical conditions distinguish NOT_ASSESSED, NONE_REPORTED and REPORTED. Reported requires entries and entries require Reported. Pregnancy and breastfeeding are explicit and never inferred from age or gender.
- Allergy entries include reaction and severity. Medicines include strength, patient-reported regimen, source, current/recently-stopped status and optional confirmation/stopped date. Laboratory results require value, unit (or explicit not applicable) and sample date. Weight requires its measurement date. Future observation dates are rejected.
- The existing Assistant free-text fields are preserved. They are not silently interpreted as structured, verified clinical information. Doctor must reconcile differences before confirming review.
- A safety review means the Doctor reviewed the recorded version, including any unknowns. It does not imply complete information or a successful drug safety assessment.
- Each Visit begins without an assessment. Previous records are Doctor-only historical context, never copied into today's current medicines. Ordinary Reception/Admin Visit and Patient APIs do not disclose these records.
- All records use UUIDs, optimistic versions, Patient then Visit database locks, request-id retry protection and transaction boundaries. Removed entries are archived and revisions remain immutable. No normal DELETE endpoint exists.
- Editing clears prior Doctor review. A recorded safety assessment must be reviewed before consultation completion. Existing Visits without a structured assessment retain their existing manual workflow. Completed records are read-only.
- Safety saves invalidate the consultation Visit version and consultation revisions snapshot the safety record. Cross-panel unsaved edits are guarded.

## Clinic UAT (fictional patient)

1. Assign an Assistant. Open Clinical Preparation and confirm only assigned Visits appear.
2. In Patient safety profile, record an allergy/reaction/severity, a reported outside medicine and source, a condition, weight/date and a result/value/unit/sample date. Confirm identity and Save safety record.
3. Reopen and verify all values. Try a contradictory None reported status with entries: save must fail and retain text. Restore correct status.
4. Submit the existing preparation. Assistant safety editing must become read-only. Another Assistant and Reception must not access it.
5. Doctor starts the assigned consultation, reads the preparation and reconciles its free-text information with the safety record. Review/edit safety and confirm the review checkbox, then save.
6. Change a safety value: prior review must be cleared unless the Doctor explicitly reviews the new version. Consultation completion with an unreviewed saved assessment must fail.
7. Review and save, review Assistant preparation, complete consultation and reopen. Both safety and clinical content are read-only.
8. Create another Visit for the same fictional patient. The previous safety record is historical and today's record starts unassessed.
9. Confirm old prescriptions, notes, diagnosis selections, billing and existing Assistant observations remain unchanged.

Release requires passing CI (API, PostgreSQL migration/concurrency and backup restore, Chromium, production web/Docker builds), then a fresh user-confirmed backup before merge/deployment. Signed-in clinic UAT remains separate from CI.
