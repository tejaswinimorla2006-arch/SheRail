"""Add trusted safety buddies, durable buddy alerts, and moderated map reports.

Revision ID: 0004_safety_buddies_and_map
Revises: 0003_safety_monitoring
"""
from alembic import op
import sqlalchemy as sa

revision = "0004_safety_buddies_and_map"
down_revision = "0003_safety_monitoring"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "safety_buddy_links",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("user_one_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("user_two_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("invited_by_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("responded_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "user_one_id <> user_two_id",
            name="ck_safety_buddy_distinct_users",
        ),
        sa.CheckConstraint(
            "invited_by_id IN (user_one_id, user_two_id)",
            name="ck_safety_buddy_inviter_is_participant",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'accepted', 'declined')",
            name="ck_safety_buddy_status",
        ),
        sa.ForeignKeyConstraint(["user_one_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_two_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["invited_by_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_one_id", "user_two_id", name="uq_safety_buddy_pair"),
    )
    op.create_index(
        "ix_safety_buddy_one_status",
        "safety_buddy_links",
        ["user_one_id", "status"],
    )
    op.create_index(
        "ix_safety_buddy_two_status",
        "safety_buddy_links",
        ["user_two_id", "status"],
    )

    op.create_table(
        "safety_buddy_alerts",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("buddy_link_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("owner_user_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("buddy_user_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("journey_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("safety_alert_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("alert_type", sa.String(length=32), nullable=False),
        sa.Column("description", sa.String(length=400), nullable=False),
        sa.Column("latitude", sa.Float(), nullable=True),
        sa.Column("longitude", sa.Float(), nullable=True),
        sa.Column("location_captured_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dedupe_key", sa.String(length=200), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["buddy_link_id"], ["safety_buddy_links.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["owner_user_id"], ["users.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["buddy_user_id"], ["users.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["journey_id"], ["journeys.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["safety_alert_id"], ["safety_alerts.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("dedupe_key", name="uq_safety_buddy_alert_dedupe_key"),
    )
    op.create_index(
        "ix_safety_buddy_alerts_recipient",
        "safety_buddy_alerts",
        ["buddy_user_id", "created_at"],
    )

    op.create_table(
        "community_safety_reports",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("report_type", sa.String(length=24), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=False),
        sa.Column("latitude", sa.Float(), nullable=False),
        sa.Column("longitude", sa.Float(), nullable=False),
        sa.Column("location_consented_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="pending", nullable=False),
        sa.Column("moderator_note", sa.String(length=300), nullable=True),
        sa.Column("verified_by_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "report_type IN ('harassment', 'theft', 'unsafe_area', 'poor_lighting', 'other')",
            name="ck_community_safety_reports_type",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'verified', 'rejected')",
            name="ck_community_safety_reports_status",
        ),
        sa.CheckConstraint(
            "latitude >= -90 AND latitude <= 90",
            name="ck_community_safety_reports_latitude",
        ),
        sa.CheckConstraint(
            "longitude >= -180 AND longitude <= 180",
            name="ck_community_safety_reports_longitude",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["verified_by_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_community_safety_reports_status_created",
        "community_safety_reports",
        ["status", "created_at"],
    )
    op.create_index(
        "ix_community_safety_reports_latitude_longitude",
        "community_safety_reports",
        ["latitude", "longitude"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_community_safety_reports_latitude_longitude",
        table_name="community_safety_reports",
    )
    op.drop_index(
        "ix_community_safety_reports_status_created",
        table_name="community_safety_reports",
    )
    op.drop_table("community_safety_reports")
    op.drop_index(
        "ix_safety_buddy_alerts_recipient",
        table_name="safety_buddy_alerts",
    )
    op.drop_table("safety_buddy_alerts")
    op.drop_index("ix_safety_buddy_two_status", table_name="safety_buddy_links")
    op.drop_index("ix_safety_buddy_one_status", table_name="safety_buddy_links")
    op.drop_table("safety_buddy_links")
