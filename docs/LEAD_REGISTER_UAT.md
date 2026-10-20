# Module 2: Lead Register

Uses the existing Phase 1 CRM, PostgreSQL database and staff logins. No schema migration is introduced. Existing appointment booking and verified Patient registration entry points remain available.

## Reception acceptance

Use fictional details and a test number, never send real messages during UAT.

1. Open Leads. Create an inquiry with name, mobile, mandatory source, branch and optional age, gender, concern and assigned staff. Source requires an explicit selection. No Patient/UHID should be created.
2. Create a second inquiry with the same mobile. Previous inquiries appear; a different inquiry can still be saved separately. Nothing is selected or merged by mobile alone.
3. Open an inquiry, edit its name/mobile/concern/source, and assign active staff at its branch. Save and reopen. Previous values remain in the Admin audit log.
4. Record a call, WhatsApp interaction or internal note. Schedule a follow-up using India Standard Time. Confirm the history and due filter. Adding an ordinary note must not erase the follow-up.
5. Edit status to Lost, select a reason and save. Reopen it using Reopen Lead. Confirm the original ID and old status/interaction history remain.
6. Mark DNC with a reason. Outbound interactions, follow-up scheduling, partner assignment and calling exports are blocked server-side; previously active partner assignments are revoked. Existing follow-up is cleared. Inbound calls and internal notes remain permitted.
7. Remove DNC only with renewed consent and an explanatory reason. Confirm both changes appear in DNC history.
8. Filter by status, owner, name/mobile and due follow-ups. Test pagination and mobile layout.
9. Open the same Lead in two browsers. Save from one, then try saving the older form: it must fail with a refresh message. Interaction/DNC/reopen writes also require the latest row_version.
10. A branch-restricted Receptionist must not read or modify another branch's Lead, including via search/detail/direct API. Staff assignment must reject an inactive, different-clinic or unauthorized owner.

## Automated verification

API tests cover the HTTP lifecycle, shared-mobile separation, no Patient creation, status/DNC/audit history, stale updates, branch boundaries, owner validation and permission denials. GitHub CI also runs these tests against PostgreSQL 16. Chromium CI exercises create/edit/assignment/follow-up/lost/reopen/DNC/inbound/shared-mobile and mobile controls, alongside the existing Staff Access regression.

Automated checks do not replace Reception acceptance of the deployed screen. Do not start another module until this checklist passes.

## Status and DNC controls

The edit form shows **Current status** separately and labels the dropdown **Change Lead status**. Staff-managed choices are New, Follow Up Required, Lost and Spam Fake. Other lifecycle statuses remain visible as disabled options with the workflow that sets them. Lost and No Show require the dedicated Reopen Lead action before changing status; Converted remains protected while demographics may still be edited.

The lifecycle Status filter excludes Do Not Call. DNC has its own **Any DNC setting / DNC on / DNC off** filter and can be combined with lifecycle, owner, search and branch restrictions. DNC continues to use the existing server-enforced flag and audited actions. No records, history or database masters are removed or migrated.

Acceptance: open a New Lead and confirm the current status and disabled workflow options; open a Lost Lead and confirm the reopening explanation; mark DNC without changing lifecycle status and verify DNC on/off and combined status filters.
