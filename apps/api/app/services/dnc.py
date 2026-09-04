from fastapi import HTTPException
from sqlalchemy import Select
from app.models.crm import Lead

OUTBOUND_PURPOSES = {
    "THIRD_PARTY_CALLING",
    "MARKETING_OUTREACH",
    "AI_OUTBOUND",
    "WHATSAPP_MARKETING",
    "SMS_MARKETING",
}


def assert_outbound_allowed(lead: Lead) -> None:
    if lead.dnc:
        raise HTTPException(
            status_code=409,
            detail="Lead cannot be used for outbound contact because Do Not Call is active",
        )


def apply_dnc_export_boundary(stmt: Select, export_purpose: str) -> Select:
    """Hard backend filter for every contact-oriented export/query."""
    if export_purpose in OUTBOUND_PURPOSES:
        return stmt.where(Lead.dnc.is_(False))
    return stmt
