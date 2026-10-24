"""Manual prescribing only; no clinical dosing or interaction automation."""
import hashlib
import json
from pathlib import Path
from fastapi import HTTPException
from sqlalchemy import select
from app.models.core import Organization
from app.models.prescription import Medicine, PrescriptionLine
from app.services.diagnoses import normalized

PRODUCT_FIELDS = ("brand", "generic", "strength", "form", "route", "pack_size", "manufacturer")
LINE_FIELDS = ("dose", "frequency", "duration", "quantity", "route", "site", "instructions")


def product_key(values):
    return hashlib.sha256(json.dumps([normalized(values.get(key, "")) for key in PRODUCT_FIELDS], ensure_ascii=False).encode()).hexdigest()


def set_search(row):
    values = {key:getattr(row,key) for key in PRODUCT_FIELDS}
    row.product_key = product_key(values)
    row.search_name = normalized(" ".join(values.values()))


def seed_medicines(db, organization_id):
    db.scalar(select(Organization).where(Organization.organization_id == organization_id).with_for_update())
    source = json.loads((Path(__file__).parent.parent / "data/medicines_v11.json").read_text())
    existing = db.scalars(select(Medicine).where(Medicine.organization_id == organization_id)).all()
    keys = {d.source_key for d in existing}
    products = {d.product_key for d in existing}
    for item in source["entries"]:
        key = f"opd-v11:Brand Strength Master:{item['source_row']}"
        pk = product_key(item)
        if key in keys or pk in products:
            continue
        row = Medicine(organization_id=organization_id, **{f:item[f] for f in PRODUCT_FIELDS},
                       active=False, requires_review=True, source_key=key, source_row=item["source_row"],
                       source_sha256=source["source_sha256"], source_verification=item["source_verification"], source_url=item["source_url"] or None)
        set_search(row);db.add(row);products.add(pk)
    db.flush()


def visit_prescriptions(db, visit_id):
    rows = db.scalars(select(PrescriptionLine).where(PrescriptionLine.visit_id == visit_id, PrescriptionLine.active.is_(True)).order_by(PrescriptionLine.display_order, PrescriptionLine.line_id)).all()
    return [{"line_id":str(r.line_id), "medicine_id":str(r.medicine_id), "medicine_version":r.medicine_version,
             **{f:getattr(r,f+"_snapshot") for f in ("brand","generic","strength","form")},
             **{f:getattr(r,f) for f in LINE_FIELDS}} for r in rows]


def set_visit_prescriptions(db, visit, doctor, organization_id, lines):
    if lines is None:
        return  # Older clients do not erase prescriptions.
    ids = [line.line_id for line in lines]
    if len(ids) != len(set(ids)):
        raise HTTPException(422, "Each prescription line needs a unique identifier")
    existing = {r.line_id:r for r in db.scalars(select(PrescriptionLine).where(PrescriptionLine.visit_id == visit.visit_id)).all()}
    # Reject client identifiers belonging to another Visit without exposing it.
    if ids and db.scalar(select(PrescriptionLine.line_id).where(PrescriptionLine.line_id.in_(ids), PrescriptionLine.visit_id != visit.visit_id)):
        raise HTTPException(422, "Prescription line identifier is unavailable")
    mids = {line.medicine_id for line in lines}
    medicines = {m.medicine_id:m for m in db.scalars(select(Medicine).where(Medicine.organization_id == organization_id, Medicine.medicine_id.in_(mids)).order_by(Medicine.medicine_id).execution_options(populate_existing=True).with_for_update()).all()} if mids else {}
    for line in lines:
        master = medicines.get(line.medicine_id)
        old = existing.get(line.line_id)
        retained = old and old.active and old.medicine_id == line.medicine_id
        if not master:
            raise HTTPException(422, "Medicine is unavailable in this organization")
        if retained:
            if line.medicine_version != old.medicine_version:
                raise HTTPException(409, "Saved medicine version changed. Refresh the consultation")
        elif not master.active or master.requires_review or master.row_version != line.medicine_version:
            raise HTTPException(409, "Medicine changed or needs review. Refresh the catalogue before prescribing")
    for row in existing.values():
        if row.active and row.line_id not in ids:
            row.active = False;row.row_version += 1
    for order,line in enumerate(lines):
        master = medicines[line.medicine_id]
        row = existing.get(line.line_id)
        keep_snapshot = row and row.active and row.medicine_id == line.medicine_id
        if not row:
            row = PrescriptionLine(line_id=line.line_id, visit_id=visit.visit_id, medicine_id=line.medicine_id, recorded_by_doctor_id=doctor.doctor_id)
            db.add(row)
        else:
            row.row_version += 1
        if not keep_snapshot:
            row.medicine_id = master.medicine_id
            row.medicine_version = master.row_version
            for key in ("brand","generic","strength","form"):
                setattr(row,key+"_snapshot",getattr(master,key))
        for key in LINE_FIELDS:
            setattr(row,key,getattr(line,key))
        row.active = True;row.display_order = order
    db.flush()
