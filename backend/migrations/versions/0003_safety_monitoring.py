"""Add journey safety monitoring, event history, and contact alert delivery records.

Revision ID: 0003_safety_monitoring
Revises: 0002_journeys
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0003_safety_monitoring"
down_revision = "0002_journeys"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "journeys",
        sa.Column("safety_monitoring_consent", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.add_column("journeys", sa.Column("checkin_interval_minutes", sa.Integer(), nullable=True))
    op.add_column(
        "journeys",
        sa.Column("checkin_grace_minutes", sa.Integer(), server_default="2", nullable=False),
    )
    op.add_column("journeys", sa.Column("checkin_due_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("journeys", sa.Column("checkin_consent_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "journeys",
        sa.Column("route_deviation_enabled", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.add_column(
        "journeys",
        sa.Column("route_deviation_threshold_m", sa.Float(), server_default="250", nullable=False),
    )
    op.add_column(
        "journeys",
        sa.Column(
            "expected_route",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column(
        "journeys",
        sa.Column("deviation_active", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.add_column("journeys", sa.Column("deviation_started_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "journeys",
        sa.Column("long_stop_enabled", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.add_column(
        "journeys",
        sa.Column("long_stop_minutes", sa.Integer(), server_default="10", nullable=False),
    )
    op.add_column(
        "journeys",
        sa.Column("stop_radius_m", sa.Float(), server_default="50", nullable=False),
    )
    op.add_column("journeys", sa.Column("stationary_since", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "journeys",
        sa.Column("long_stop_alerted_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "safety_events",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("journey_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column(
            "details",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("latitude", sa.Float(), nullable=True),
        sa.Column("longitude", sa.Float(), nullable=True),
        sa.Column("location_captured_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dedupe_key", sa.String(length=200), nullable=False),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["journey_id"], ["journeys.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("dedupe_key", name="uq_safety_events_dedupe_key"),
    )
    op.create_index(
        "ix_safety_events_user_status",
        "safety_events",
        ["user_id", "status", "occurred_at"],
    )

    op.create_table(
        "safety_alerts",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("journey_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("safety_event_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("alert_type", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=24), server_default="pending", nullable=False),
        sa.Column("trigger_key", sa.String(length=200), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=False),
        sa.Column(
            "journey_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("latitude", sa.Float(), nullable=True),
        sa.Column("longitude", sa.Float(), nullable=True),
        sa.Column("location_captured_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["journey_id"], ["journeys.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["safety_event_id"], ["safety_events.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("trigger_key", name="uq_safety_alerts_trigger_key"),
    )
    op.create_index(
        "ix_safety_alerts_user_created",
        "safety_alerts",
        ["user_id", "created_at"],
    )

    op.create_table(
        "safety_alert_deliveries",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("alert_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("contact_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("contact_name", sa.String(length=120), nullable=False),
        sa.Column("phone", sa.String(length=32), nullable=False),
        sa.Column("message_type", sa.String(length=16), server_default="initial", nullable=False),
        sa.Column("status", sa.String(length=24), server_default="pending", nullable=False),
        sa.Column("provider_message_id", sa.String(length=64), nullable=True),
        sa.Column("last_error", sa.String(length=500), nullable=True),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["alert_id"], ["safety_alerts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["contact_id"], ["emergency_contacts.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider_message_id"),
        sa.UniqueConstraint(
            "alert_id",
            "contact_id",
            "message_type",
            name="uq_safety_alert_delivery",
        ),
    )
    op.create_index(
        "ix_safety_alert_deliveries_status",
        "safety_alert_deliveries",
        ["status", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_safety_alert_deliveries_status", table_name="safety_alert_deliveries")
    op.drop_table("safety_alert_deliveries")
    op.drop_index("ix_safety_alerts_user_created", table_name="safety_alerts")
    op.drop_table("safety_alerts")
    op.drop_index("ix_safety_events_user_status", table_name="safety_events")
    op.drop_table("safety_events")
    for column in (
        "long_stop_alerted_at",
        "stationary_since",
        "stop_radius_m",
        "long_stop_minutes",
        "long_stop_enabled",
        "deviation_started_at",
        "deviation_active",
        "expected_route",
        "route_deviation_threshold_m",
        "route_deviation_enabled",
        "checkin_consent_at",
        "checkin_due_at",
        "checkin_grace_minutes",
        "checkin_interval_minutes",
        "safety_monitoring_consent",
    ):
        op.drop_column("journeys", column)
