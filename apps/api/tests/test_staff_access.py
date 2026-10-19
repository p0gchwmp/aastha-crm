"""HTTP account lifecycle; STAFF_TEST_DATABASE_URL enables disposable PostgreSQL tests."""
import os
import uuid
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from app.core.db import get_db
from app.core.security import hash_password
from app.main import app
from app.models import Base
from app.models.core import Organization, Branch, User, Role, Permission, RolePermission, UserRole
from app.models.integration import AuditEvent

TEMP = "R3ception!Start2026"
NEW = "R3ception!Private2026"
RESET = "R3ception!Reset2026"

@pytest.fixture
def clinic():
    url = os.getenv("STAFF_TEST_DATABASE_URL")
    if url:
        engine = create_engine(url)
    else:
        engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        @event.listens_for(engine, "connect")
        def attach(connection, _):
            for schema in {t.schema for t in Base.metadata.tables.values() if t.schema}:
                connection.execute(f"ATTACH DATABASE ':memory:' AS {schema}")
        Base.metadata.create_all(engine, tables=[m.__table__ for m in (Organization, Branch, User, Role, Permission, RolePermission, UserRole, AuditEvent)])
        with engine.begin() as c:
            c.execute(text("CREATE UNIQUE INDEX core.ux_users_login ON users(lower(username))"))
    db = Session(engine, expire_on_commit=False)
    orgs = [Organization(organization_code=f"T{uuid.uuid4().hex[:10]}", organization_name="Test clinic") for _ in range(2)]
    db.add_all(orgs); db.flush()
    branches = [Branch(organization_id=orgs[i//2].organization_id, branch_code=str(i), branch_name=f"Branch {i}") for i in range(3)]
    db.add_all(branches); db.flush()
    roles = {}
    for code in ("ADMIN", "RECEPTIONIST", "SUPER_RECEPTIONIST", "DOCTOR", "SUPER_ADMIN"):
        role = db.scalar(select(Role).where(Role.code == code))
        if not role:
            role = Role(code=code, name=code); db.add(role); db.flush()
        roles[code] = role
    p = db.scalar(select(Permission).where(Permission.code == "STAFF_MANAGE"))
    if not p:
        p = Permission(code="STAFF_MANAGE", name="Staff"); db.add(p); db.flush()
    if not db.scalar(select(RolePermission).where(RolePermission.role_id == roles["ADMIN"].role_id, RolePermission.permission_id == p.permission_id)):
        db.add(RolePermission(role_id=roles["ADMIN"].role_id, permission_id=p.permission_id))
    users = {}
    for code in ("ADMIN", "RECEPTIONIST", "DOCTOR", "SUPER_ADMIN"):
        u = User(organization_id=orgs[0].organization_id, username=f"u{uuid.uuid4().hex}", name=code, password_hash=hash_password(NEW), status="ACTIVE")
        db.add(u); db.flush()
        db.add(UserRole(user_id=u.user_id, role_id=roles[code].role_id, branch_id=branches[0].branch_id if code == "RECEPTIONIST" else None))
        users[code] = u
    db.commit()
    def override():
        try: yield db
        except Exception:
            db.rollback()
            raise
    app.dependency_overrides[get_db] = override
    with TestClient(app, base_url="http://localhost") as client:
        def login(username, password=NEW):
            r = client.post("/api/v1/auth/login", json={"username":username,"password":password})
            assert r.status_code == 200, r.text
            return {"Authorization":f"Bearer {r.json()['access_token']}"}
        yield client, db, branches, users, login(users["ADMIN"].username), login
    app.dependency_overrides.clear()
    db.close(); engine.dispose()

def create(clinic, **extra):
    client, _, branches, _, headers, _ = clinic
    payload = {"name":"Test receptionist", "username":f"new{uuid.uuid4().hex[:12]}", "role":"RECEPTIONIST", "branch_ids":[str(branches[0].branch_id)], "temporary_password":TEMP}
    payload.update(extra)
    return client.post("/api/v1/admin/staff", headers=headers, json=payload)

def test_complete_reception_account_lifecycle(clinic):
    c, db, branches, _, admin, login = clinic
    r = create(clinic); assert r.status_code == 201, r.text
    staff = r.json(); uid = staff["user_id"]
    assert "password_hash" not in staff and "temporary_password" not in staff
    old = login(staff["username"], TEMP)
    assert c.get("/api/v1/auth/me", headers=old).json()["must_change_password"] is True
    assert c.get("/api/v1/meta/bootstrap", headers=old).status_code == 403
    assert c.post("/api/v1/auth/change-password", headers=old, json={"current_password":TEMP,"new_password":NEW}).status_code == 200
    assert c.get("/api/v1/auth/me", headers=old).status_code == 401
    reception = login(staff["username"].upper())
    me = c.get("/api/v1/auth/me", headers=reception).json()
    assert me["branch_ids"] == [str(branches[0].branch_id)] and me["must_change_password"] is False
    assert c.get("/api/v1/admin/staff", headers=reception).status_code == 403
    staff = next(u for u in c.get("/api/v1/admin/staff", headers=admin).json()["users"] if u["user_id"] == uid)
    update = {"name":"Updated", "role":"SUPER_RECEPTIONIST", "branch_ids":[str(branches[1].branch_id)], "status":"ACTIVE", "row_version":staff["row_version"], "reason":"Branch reassignment"}
    r = c.patch(f"/api/v1/admin/staff/{uid}", headers=admin, json=update); assert r.status_code == 200, r.text
    staff = r.json()
    assert c.get("/api/v1/auth/me", headers=reception).status_code == 401
    assert c.patch(f"/api/v1/admin/staff/{uid}", headers=admin, json=update).status_code == 409
    reception = login(staff["username"])
    assert c.get("/api/v1/auth/me", headers=reception).json()["branch_ids"] == [str(branches[1].branch_id)]
    r = c.post(f"/api/v1/admin/staff/{uid}/reset-password", headers=admin, json={"temporary_password":RESET,"row_version":staff["row_version"],"reason":"Forgot credentials"}); assert r.status_code == 200, r.text
    staff = r.json()
    assert c.get("/api/v1/auth/me", headers=reception).status_code == 401
    assert c.post("/api/v1/auth/login", json={"username":staff["username"],"password":NEW}).status_code == 401
    reset_session = login(staff["username"], RESET)
    assert c.get("/api/v1/meta/bootstrap", headers=reset_session).status_code == 403
    update.update(row_version=staff["row_version"], status="INACTIVE")
    assert c.patch(f"/api/v1/admin/staff/{uid}", headers=admin, json=update).status_code == 200
    assert c.get("/api/v1/auth/me", headers=reset_session).status_code == 401
    assert c.post("/api/v1/auth/login", json={"username":staff["username"],"password":RESET}).status_code == 401
    events = db.scalars(select(AuditEvent).where(AuditEvent.entity_id == uuid.UUID(uid))).all()
    assert {e.action for e in events} >= {"STAFF_CREATED","STAFF_UPDATED","STAFF_PASSWORD_RESET","PASSWORD_CHANGED"}
    from app.core.access import ensure_branch_access
    from fastapi import HTTPException
    target = db.get(User, uuid.UUID(uid))
    with pytest.raises(HTTPException) as denied:
        ensure_branch_access(db, target, branches[0].branch_id)
    assert denied.value.status_code == 403
    for e in events:
        serialized = str(e.before_data)+str(e.after_data)
        assert all(secret not in serialized for secret in (TEMP,NEW,RESET,"password_hash"))

def test_staff_boundaries_and_duplicate_usernames(clinic):
    c, _, branches, users, admin, login = clinic
    assert c.get("/api/v1/admin/staff").status_code == 401
    for code in ("RECEPTIONIST","DOCTOR"):
        assert c.get("/api/v1/admin/staff", headers=login(users[code].username)).status_code == 403
    assert create(clinic, role="ADMIN").status_code == 422
    assert create(clinic, branch_ids=[]).status_code == 422
    assert create(clinic, branch_ids=[str(branches[2].branch_id)]).status_code == 422
    assert create(clinic, temporary_password="short").status_code == 422
    assert create(clinic, username=users["ADMIN"].username.upper()).status_code == 409
    r = create(clinic); assert r.status_code == 201
    assert create(clinic, username=r.json()["username"].upper()).status_code == 409
    payload = {"name":"Attempt", "role":"RECEPTIONIST", "branch_ids":[str(branches[0].branch_id)], "status":"INACTIVE", "row_version":1, "reason":"Try privileged account"}
    for code in ("ADMIN","SUPER_ADMIN","DOCTOR"):
        assert c.patch(f"/api/v1/admin/staff/{users[code].user_id}", headers=admin, json=payload).status_code == 403
    assert c.patch(f"/api/v1/admin/staff/{uuid.uuid4()}", headers=admin, json=payload).status_code == 404
