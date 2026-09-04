import hashlib
from fastapi import Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.core.db import get_db
from app.models.integration import IntegrationClient


def hash_integration_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def integration_client(
    x_integration_key: str | None = Header(default=None, alias="X-Integration-Key"),
    db: Session = Depends(get_db),
) -> IntegrationClient:
    if not x_integration_key:
        raise HTTPException(401, "Missing integration credential")
    digest = hash_integration_key(x_integration_key)
    client = db.scalar(
        select(IntegrationClient).where(
            IntegrationClient.credential_hash == digest,
            IntegrationClient.status == "ACTIVE",
        )
    )
    if not client:
        raise HTTPException(401, "Invalid integration credential")
    return client


def require_integration_scope(scope: str):
    def dependency(client: IntegrationClient = Depends(integration_client)) -> IntegrationClient:
        scopes = client.allowed_scopes or {}
        allowed = scopes.get("scopes", []) if isinstance(scopes, dict) else []
        if scope not in allowed:
            raise HTTPException(403, f"Missing integration scope: {scope}")
        return client
    return dependency
