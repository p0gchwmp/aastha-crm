"""initial modular CRM schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-09-03
"""
from alembic import op
from app.models import Base

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None

SCHEMAS = [
    "core",
    "crm",
    "patient",
    "scheduling",
    "clinical",
    "consultation_finance",
    "integration",
    "audit",
    "reporting",
]


def upgrade():
    for schema in SCHEMAS:
        op.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind, checkfirst=True)


def downgrade():
    for schema in reversed(SCHEMAS):
        op.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
