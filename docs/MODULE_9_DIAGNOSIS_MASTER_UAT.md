# Module 9: Diagnosis Master

## Scope and source

Source: `Aastha_Dermatology_OPD_Clinical_System_v11 (1)(1).xlsx`, Diagnosis Master, header row 4, data rows 5–188. The JSON catalogue records the original workbook SHA-256 and source row for every entry.

184 entries are imported per organization: 181 active, 3 inactive and awaiting clinical review:

- Cystic acne lesion – intralesional treatment
- Post-procedure pain / inflammation
- PUVA / trioxsalen photochemotherapy – vitiligo

These entries need classification/wording review; authorized users can correct, approve and activate them. The classification is not a clinical judgment. Medicine suggestions, dose rules, traffic-light rules and clinical notes from the workbook are excluded from this module.

Doctors and Admin/Super Admin receive `DIAGNOSIS_MASTER_MANAGE`. Reception and Clinical Assistants do not. Catalogue access does not grant access to patient diagnoses. Only the assigned Doctor can record diagnoses through the existing consultation endpoint, within its branch/organization restrictions.

## Behaviour

- Search by name/category; paginated catalogue; add/edit/deactivate without hard deletion.
- Name uniqueness is enforced per organization after Unicode/whitespace/case normalization, including inactive names.
- Catalogue changes require a reason and current row version and create audit records.
- Each Visit supports up to 20 distinct diagnoses, exactly one primary when any are selected.
- Diagnosis selection and Doctor notes save together in the existing locked, transactional, idempotent note-save operation. A selected diagnosis is not saved until Save Notes or Complete succeeds.
- Removing a selection archives its relational link. Consultation revision snapshots retain previous selections.
- Master renames/deactivation do not rewrite existing selections or historical snapshots. Existing inactive diagnoses can remain on their original Visit; they cannot be newly selected elsewhere.
- Completed consultations remain read-only. Older clients omitting the diagnoses field preserve existing selections.
- Existing consultations with no structured diagnoses continue to work. This release does not force diagnoses onto old records or auto-create diagnoses from narrative assessments.

## Deployment and migration

Fresh downloaded clinic backup is required before merge/deployment, following the user's existing backup rule. Deployment remains manual. Migration `0013_diagnosis_master` adds `clinical.diagnoses` and `clinical.visit_diagnoses`; no existing clinical or financial rows are altered. Bootstrap is idempotent and preserves user edits, including deactivated source entries. Do not downgrade a live clinic database: downgrade checks are only for disposable CI databases.

## Clinic acceptance after deployment

1. Sign out/in as Admin. Open Diagnosis Master; search for an existing diagnosis. Include inactive/awaiting-review entries and confirm the three held items.
2. Add a clearly named test diagnosis and category. Edit it with a reason. Confirm a duplicate name and a stale edit are rejected.
3. Sign in as the assigned Doctor. Start a test consultation using current Patient identity verification.
4. Add two diagnoses, choose one primary, Save Notes, refresh, and verify both selections and the primary indicator.
5. Remove one diagnosis, save, and verify the earlier selection remains in Saved versions.
6. Rename/deactivate a diagnosis in the master. Reopen the saved Visit: its recorded name must remain unchanged. A new Visit must not offer the inactive entry.
7. Complete the consultation. Reopen it and verify selections are read-only and appear in Doctor-only Patient history.
8. Verify Reception and Assistant accounts cannot open Diagnosis Master or receive patient diagnoses from ordinary Visit/Patient-history APIs.
9. Recheck the previously accepted Assistant submission → Doctor review → note save → completion workflow.

Manual clinic acceptance is pending. CI evidence is recorded in the pull request; CI uses disposable fictional records and does not certify live clinic data entry.
