"""Phase 0 smoke marker only; not a production market or trading schema."""

import sqlalchemy as sa
from alembic import op

revision = "0001_fixture"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "fixture_marker",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("value", sa.Numeric(38, 18), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        schema="ops",
    )


def downgrade() -> None:
    op.drop_table("fixture_marker", schema="ops")
