# Module 3: Appointment Booking and Doctor Schedules

## Scope

The existing Phase 1 CRM now uses one availability engine for reception booking, Lead booking and API requests. It supports multiple recurring clinic windows, effective dates, slot length, full-day leave/holiday/closure, partial breaks and additional clinics. No timings are invented for a fresh installation. Existing schedules remain available for Admin review, with overlap warnings; bootstrap never recreates deleted/changed default timings.

A doctor can have only one overlapping active appointment across all branches. Booking, rescheduling, attendance and schedule changes lock the doctor row in PostgreSQL. New booking requests can carry `booking_request_id`; identical retries from the same user return the original appointment, and changed payloads using the same key fail. A database unique index is the final retry safeguard.

Lead and registered Patient selection is explicit. Shared-mobile search never auto-selects or merges anyone. Booking/attendance creates no Patient or UHID. Verified conversion may attach a Patient later while retaining the original Lead. Appointment booking remains permitted for inbound DNC inquiries; DNC flags and outbound restrictions remain in effect.

## Reception acceptance — fictional details only

1. Ask Admin to configure real approved branch/doctor clinic windows. Review any warning about old overlapping schedules. Do not silently assume the previous development seed timings are correct.
2. In Leads, open an inquiry and Book appointment. Choose branch, doctor, date and an available slot. Confirm Lead becomes Appointment Booked without Patient/UHID creation.
3. From Appointments, use Book appointment. Search Leads or registered Patients and explicitly select the correct record. Patient choices show UHID and age/gender/mobile where recorded.
4. In another browser/terminal, try the same doctor/time, including at another branch: only one booking may succeed. Refreshing slots removes occupied times. Retrying the identical booking request must return the same appointment ID.
5. Reschedule an appointment with a reason. Old time becomes free, the new time is reserved and history shows both times. Two stale edits must not overwrite each other.
6. Confirm, mark arrived and complete an appointment. Mark arrived is separate from verified Patient registration and does not create a Visit or UHID.
7. No-show requires a reason, cannot be marked before the appointment time, and moves an unconverted Lead to No Show only when no other active appointment remains. Reopen that Lead through the Lead workflow when appropriate.
8. Cancel with a reason. The record/history remain, the slot becomes free, and the Lead returns to Follow Up Required when no other active appointment remains. No outbound follow-up is automatically scheduled.
9. Closed attendance states cannot be silently reactivated; create a new appointment for a new encounter. A checked-in appointment cannot be marked no-show. A completed appointment is not a completed clinical Visit.
10. Check date, branch, doctor and attendance filters, appointment history, mobile layout, and branch-restricted staff access. Reception cannot configure doctor schedules without the dedicated permission.

## Admin acceptance

1. Appointments → Doctor schedules → Add clinic window. Select doctor, branch, weekday, start/end, slot length, effective From/Until and reason. Times are IST.
2. Add separate morning/evening windows. Overlapping windows, including at different branches, must fail. Deactivate/correct old conflicting windows explicitly.
3. Edit a window. Stale saves fail. Existing booked appointments are not moved or cancelled by changing availability; affected changes are rejected until staff resolves those appointments.
4. Add a leave/holiday/closure, partial break or additional clinic. Availability and booking must agree. Additional clinics require times and cannot overlap existing clinics.
5. Cancel an exception with a reason. It remains in history; additional clinics with bookings cannot be removed implicitly.
6. Review Admin Audit for schedule, exception and appointment changes.

## Migration and deployment

`0007_appointments` adds nullable booking request ID/hash columns and a unique index, a doctor/time lookup index, version/timestamp/slot/note fields for schedule exceptions, and the dedicated `APPOINTMENT_SCHEDULE_MANAGE` permission for Admin/Super Admin. It does not replace operational identities, move appointments, generate Patients or import finance.

A fresh, durable database backup/recovery point is required before deployment/migration under the frozen project rules. Test blank and populated PostgreSQL migration, concurrency, booking/attendance, browser flows and logical backup/restore before API-first deployment. The saved staff/passwords and existing clinic data must survive. Never restore the live database as a routine test; restore only into a separate disposable database.

## Validation scope

CI runs the HTTP appointment suite against PostgreSQL 16, including simultaneous cross-branch booking and simultaneous retries, plus migration/backup/restore and Chromium schedule/booking/rescheduling/cancellation/attendance. Manual Reception/Admin acceptance on the deployed clinic environment is still required.
