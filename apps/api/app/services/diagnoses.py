"""Catalogue bootstrap and diagnosis updates within the consultation transaction."""
import json
import unicodedata
from pathlib import Path
from fastapi import HTTPException
from sqlalchemy import select
from app.models.core import Organization
from app.models.diagnosis import Diagnosis, VisitDiagnosis


def normalized(value):
    return " ".join(unicodedata.normalize("NFKC", value).split()).casefold()


def seed_catalogue(db, organization_id):
    # Serializes catalogue writers; source keys survive user renames/deactivation.
    db.scalar(select(Organization).where(Organization.organization_id == organization_id).with_for_update())
    source = json.loads((Path(__file__).parent.parent / "data/diagnoses_v11.json").read_text())
    existing = db.scalars(select(Diagnosis).where(Diagnosis.organization_id == organization_id)).all()
    keys = {d.source_key for d in existing}
    names = {d.normalized_name for d in existing}
    for row in source["entries"]:
        key = f"opd-v11:Diagnosis Master:{row['source_row']}"
        name_key = normalized(row["name"])
        if key in keys or name_key in names:
            continue
        db.add(Diagnosis(organization_id=organization_id, name=row["name"], normalized_name=name_key,
                         category=row["category"], history_module=row["history_module"] or None,
                         active=not row["requires_review"], requires_review=row["requires_review"],
                         source_key=key, source_row=row["source_row"], source_sha256=source["source_sha256"]))
        names.add(name_key)
    db.flush()


def visit_diagnoses(db, visit_id):
    return [{"diagnosis_id": d.diagnosis_id, "name": d.name_snapshot, "category": d.category_snapshot,
             "is_primary": d.is_primary} for d in db.scalars(select(VisitDiagnosis).where(
                 VisitDiagnosis.visit_id == visit_id, VisitDiagnosis.active.is_(True)
             ).order_by(VisitDiagnosis.is_primary.desc(), VisitDiagnosis.name_snapshot, VisitDiagnosis.diagnosis_id)).all()]


def set_visit_diagnoses(db, visit, doctor, organization_id, selections):
    if selections is None:
        return  # Older clients preserve the saved selection.
    ids = [x.diagnosis_id for x in selections]
    if len(ids) != len(set(ids)) or (ids and sum(x.is_primary for x in selections) != 1):
        raise HTTPException(422, "Choose unique diagnoses and exactly one primary diagnosis")
    current = {d.diagnosis_id: d for d in db.scalars(select(VisitDiagnosis).where(VisitDiagnosis.visit_id == visit.visit_id)).all()}
    masters = {d.diagnosis_id: d for d in db.scalars(select(Diagnosis).where(
        Diagnosis.organization_id == organization_id, Diagnosis.diagnosis_id.in_(ids)
    ).order_by(Diagnosis.diagnosis_id).execution_options(populate_existing=True).with_for_update()).all()} if ids else {}
    for selection in selections:
        master = masters.get(selection.diagnosis_id)
        old = current.get(selection.diagnosis_id)
        if not master:
            raise HTTPException(422, "Diagnosis is unavailable in this organization")
        if (not master.active or master.requires_review) and not (old and old.active):
            raise HTTPException(409, "A selected diagnosis is inactive or awaiting review. Refresh the catalogue")
    for row in current.values():
        if row.active and row.diagnosis_id not in ids:
            row.active = False
            row.is_primary = False
            row.row_version += 1
    for selection in selections:
        master = masters[selection.diagnosis_id]
        row = current.get(selection.diagnosis_id)
        if not row:
            row = VisitDiagnosis(visit_id=visit.visit_id, diagnosis_id=master.diagnosis_id,
                name_snapshot=master.name, category_snapshot=master.category, recorded_by_doctor_id=doctor.doctor_id)
            db.add(row)
        elif not row.active:
            row.name_snapshot, row.category_snapshot = master.name, master.category
            row.recorded_by_doctor_id = doctor.doctor_id
            row.row_version += 1
        elif row.is_primary != selection.is_primary:
            row.row_version += 1
        row.active = True
        row.is_primary = selection.is_primary
    db.flush()
