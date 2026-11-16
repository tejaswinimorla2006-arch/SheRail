"""Add journey tracking, route points, and per-recipient sharing.

Revision ID: 0002_journeys
Revises: 0001_initial
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0002_journeys"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "journeys",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("transport_mode", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="planned", nullable=False),
        sa.Column("origin", sa.String(length=160), nullable=True),
        sa.Column("destination", sa.String(length=160), nullable=True),
        sa.Column(
            "transport_details",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "location_recording_enabled",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
        sa.Column("location_consent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sharing_enabled", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("paused_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "transport_mode IN ('walking', 'bus', 'train', 'metro', 'cab')",
            name="ck_journeys_transport_mode",
        ),
        sa.CheckConstraint(
            "status IN ('planned', 'active', 'paused', 'completed')",
            name="ck_journeys_status",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_journeys_user_created", "journeys", ["user_id", "created_at"])

    op.create_table(
        "journey_locations",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("journey_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("latitude", sa.Float(), nullable=False),
        sa.Column("longitude", sa.Float(), nullable=False),
        sa.Column("accuracy_m", sa.Float(), nullable=True),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "latitude >= -90 AND latitude <= 90",
            name="ck_journey_locations_latitude",
        ),
        sa.CheckConstraint(
            "longitude >= -180 AND longitude <= 180",
            name="ck_journey_locations_longitude",
        ),
        sa.ForeignKeyConstraint(["journey_id"], ["journeys.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_journey_locations_route",
        "journey_locations",
        ["journey_id", "captured_at"],
    )

    op.create_table(
        "journey_events",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("journey_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.String(length=40), nullable=False),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["journey_id"], ["journeys.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_journey_events_timeline",
        "journey_events",
        ["journey_id", "occurred_at"],
    )

    op.create_table(
        "journey_shares",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("journey_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("recipient_user_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["journey_id"], ["journeys.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["recipient_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "journey_id",
            "recipient_user_id",
            name="uq_journey_share_recipient",
        ),
    )
    op.create_index("ix_journey_shares_journey_id", "journey_shares", ["journey_id"])
    op.create_index(
        "ix_journey_shares_recipient_user_id",
        "journey_shares",
        ["recipient_user_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_journey_shares_recipient_user_id", table_name="journey_shares")
    op.drop_index("ix_journey_shares_journey_id", table_name="journey_shares")
    op.drop_table("journey_shares")
    op.drop_index("ix_journey_events_timeline", table_name="journey_events")
    op.drop_table("journey_events")
    op.drop_index("ix_journey_locations_route", table_name="journey_locations")
    op.drop_table("journey_locations")
    op.drop_index("ix_journeys_user_created", table_name="journeys")
    op.drop_table("journeys")
