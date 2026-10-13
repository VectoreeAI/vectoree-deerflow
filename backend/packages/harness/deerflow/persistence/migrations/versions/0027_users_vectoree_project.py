"""scope user emails to a Vectoree project.

Revision ID: 0027_users_vectoree_project
Revises: 0026_mcp_task_lease_tokens
Create Date: 2026-10-13

Cloud previews serve many Vectoree projects from one database, so the same
email must be able to exist once per project. Adds ``users.vectoree_project_id``
(``''`` for every existing and local account), demotes ``ix_users_email`` to a
plain lookup index and enforces uniqueness on ``(vectoree_project_id, email)``.

Downgrade restores the global unique email index; it fails if two projects
already hold the same email, which must be cleaned up first.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0027_users_vectoree_project"
down_revision: str | Sequence[str] | None = "0026_mcp_task_lease_tokens"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_EMAIL_INDEX = "ix_users_email"
_PROJECT_EMAIL_INDEX = "uq_users_project_email"


def _indexes() -> dict[str, dict]:
    return {index["name"]: index for index in sa.inspect(op.get_bind()).get_indexes("users")}


def upgrade() -> None:
    from deerflow.persistence.migrations._helpers import safe_add_column

    safe_add_column("users", sa.Column("vectoree_project_id", sa.String(length=64), nullable=False, server_default=""))
    indexes = _indexes()
    if indexes.get(_EMAIL_INDEX, {}).get("unique"):
        op.drop_index(_EMAIL_INDEX, table_name="users")
        indexes.pop(_EMAIL_INDEX)
    if _EMAIL_INDEX not in indexes:
        op.create_index(_EMAIL_INDEX, "users", ["email"], unique=False)
    if _PROJECT_EMAIL_INDEX not in indexes:
        op.create_index(_PROJECT_EMAIL_INDEX, "users", ["vectoree_project_id", "email"], unique=True)


def downgrade() -> None:
    from deerflow.persistence.migrations._helpers import safe_drop_column

    indexes = _indexes()
    if _PROJECT_EMAIL_INDEX in indexes:
        op.drop_index(_PROJECT_EMAIL_INDEX, table_name="users")
    if _EMAIL_INDEX in indexes and not indexes[_EMAIL_INDEX].get("unique"):
        op.drop_index(_EMAIL_INDEX, table_name="users")
        indexes.pop(_EMAIL_INDEX)
    if _EMAIL_INDEX not in indexes:
        op.create_index(_EMAIL_INDEX, "users", ["email"], unique=True)
    safe_drop_column("users", "vectoree_project_id")
