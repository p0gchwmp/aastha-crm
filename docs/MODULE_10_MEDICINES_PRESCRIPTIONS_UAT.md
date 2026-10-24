# Module 10: Medicine Catalogue and manual prescriptions

## Source and scope

Source: `Aastha_Dermatology_OPD_Clinical_System_v11 (1)(1).xlsx`, Brand Strength Master, header row 4. All 352 source products are preserved with row numbers and workbook SHA-256. 294 have no mapped generic/composition or form. Missing strengths/compositions are not inferred from brand names or other reference sheets.

All imported products start inactive and awaiting Doctor review, including entries labelled verified in the workbook. The workbook verification wording is retained as source information, not treated as CRM Doctor approval. Stock quantities, costs, MRP, supplier data, finance, dose rules and interaction automation are excluded. This module does not import the separate generic/formulary sheets or create injection administration or procedure orders.

Catalogue products have permanent UUIDs, composition, optional brand, exact strength, form, route, optional pack and manufacturer. Admin and Doctor can maintain drafts; only a linked active Doctor with MEDICINE_MASTER_VERIFY can confirm product details. Activation requires reviewed composition, strength, form and route. Where a product has no applicable strength, the Doctor must explicitly enter an appropriate description rather than leave it blank.

Any substantive product change requires fresh Doctor review. Source edits are preserved across bootstrap/deploys. Catalogue changes use row versions and audit reasons. No hard-delete endpoint is provided.

## Prescription behaviour

- Only the Visit's assigned Doctor can prescribe, after identity verification and starting the consultation, within existing branch/organization controls.
- Up to 30 medicine lines per Visit. Each line has a stable UUID; separate lines allow distinct regimens for one product.
- Dose/amount, route, frequency and duration are required Doctor-entered text. Quantity, site and instructions are optional. No dosing, renal, paediatric, pregnancy, interaction or diagnosis-based treatment decisions are automated.
- Selection uses only active, Doctor-reviewed products. The chosen product version must still match at save; changed strengths/products require refresh rather than silent substitution.
- Medicines save atomically with Doctor notes and diagnoses, using existing request replay and Visit version protection. Unsaved changes use the existing navigation guard.
- Product name, composition, strength and form are captured per line. Catalogue edits/deactivation cannot rewrite saved prescriptions; existing retained lines can remain on their original Visit.
- Removing a line archives it; revision snapshots retain its earlier contents. Completed consultations are read-only. Older clients omitting prescriptions preserve current lines.
- Prescriptions appear only in the protected Doctor detail/history/revision responses. Ordinary Reception/Assistant Visit and Patient-history APIs do not expose them.

Printing is a later module. No pharmacy stock, dispensing, medicine billing or procedure finance is introduced.

## Upgrade and testing

Additive migration 0014_prescriptions creates clinical.medicines and clinical.prescription_lines, grants permissions and imports catalogue drafts. It does not change Patient, UHID, Visit identity, consultation payments or existing diagnoses/notes/handover rows. A fresh downloaded backup is required before deployment/migration under the user's existing rule. Never downgrade the live clinic database; downgrade tests use disposable CI databases.

CI covers populated data preservation, concurrent saves, logical backup/restore with exact medicine/prescription row comparisons, production images and Chromium workflow. Manual clinic acceptance remains pending until deployment and user testing.

## Clinic UAT

1. Sign out/in as Doctor. Open Medicine Catalogue, search for a known brand, and inspect the workbook source note and missing details.
2. Confirm its exact composition, strength, form and route against the clinic's product, enter any missing information, tick the Doctor verification confirmation and Active for prescribing, enter a reason, and save. Alternatively add a clearly labelled test product for UAT.
3. Sign in as Admin: confirm drafts can be maintained, but Doctor verification cannot be performed. Reception and Assistant should have no Medicine Catalogue link/access.
4. Open an assigned in-progress test consultation. Search and select two reviewed products. Verify dose/frequency/duration begin blank, then enter the intended test prescription details. Save Notes.
5. Reopen the Visit and confirm both medicine lines, strengths and every entered instruction remain saved.
6. Edit/deactivate the catalogue product. Its recorded Visit prescription must retain the original product details. A newly selected product changed before save must trigger a conflict rather than adopt a different strength.
7. Remove a medicine line and save; confirm the earlier version remains in Saved versions. Complete the consultation and reopen it; prescriptions must be visible and read-only.
8. Confirm the protected Doctor Patient history displays the previous prescription, while Reception/Assistant cannot read it.
9. Recheck diagnosis entry and Assistant → Doctor preparation review. Existing finance and registration workflows should continue unchanged.
