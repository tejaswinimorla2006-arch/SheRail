"""Add report media, admin roles, verified help, railway data, and notifications.

Revision ID: 0005_admin_notifications
Revises: 0004_safety_buddies_and_map
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0005_admin_notifications"
down_revision = "0004_safety_buddies_and_map"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("role", sa.String(length=16), server_default="user", nullable=False),
    )
    op.add_column(
        "users",
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
    )
    op.create_check_constraint("ck_users_role", "users", "role IN ('user', 'admin')")

    op.add_column(
        "safety_alerts",
        sa.Column("admin_status", sa.String(length=16), server_default="open", nullable=False),
    )
    op.add_column("safety_alerts", sa.Column("admin_note", sa.String(length=500), nullable=True))
    op.add_column(
        "safety_alerts",
        sa.Column("admin_reviewed_by_id", sa.Uuid(as_uuid=True), nullable=True),
    )
    op.add_column(
        "safety_alerts",
        sa.Column("admin_reviewed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_check_constraint(
        "ck_safety_alerts_admin_status",
        "safety_alerts",
        "admin_status IN ('open', 'investigating', 'resolved', 'dismissed')",
    )
    op.create_foreign_key(
        "fk_safety_alerts_admin_reviewed_by",
        "safety_alerts",
        "users",
        ["admin_reviewed_by_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.drop_constraint(
        "ck_community_safety_reports_status",
        "community_safety_reports",
        type_="check",
    )
    op.create_check_constraint(
        "ck_community_safety_reports_status",
        "community_safety_reports",
        "status IN ('pending', 'under_review', 'verified', 'rejected', 'duplicate')",
    )
    op.add_column(
        "community_safety_reports",
        sa.Column("duplicate_of_id", sa.Uuid(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_community_safety_reports_duplicate_of",
        "community_safety_reports",
        "community_safety_reports",
        ["duplicate_of_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_community_safety_reports_duplicate",
        "community_safety_reports",
        ["duplicate_of_id"],
    )

    op.create_table(
        "community_safety_report_images",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("report_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("media_type", sa.String(length=32), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("content", sa.LargeBinary(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["report_id"], ["community_safety_reports.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("report_id", "sha256", name="uq_safety_report_image_hash"),
    )
    op.create_index(
        "ix_safety_report_images_report",
        "community_safety_report_images",
        ["report_id"],
    )

    op.create_table(
        "verified_assistance_points",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=True),
        sa.Column("address", sa.String(length=300), nullable=True),
        sa.Column("phone", sa.String(length=32), nullable=True),
        sa.Column("latitude", sa.Float(), nullable=False),
        sa.Column("longitude", sa.Float(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("created_by_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("updated_by_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "category IN ('police', 'hospital', 'clinic', 'shelter', 'crisis_center', 'assistance_point', 'railway_assistance')",
            name="ck_verified_assistance_points_category",
        ),
        sa.CheckConstraint("latitude >= -90 AND latitude <= 90", name="ck_assistance_points_latitude"),
        sa.CheckConstraint("longitude >= -180 AND longitude <= 180", name="ck_assistance_points_longitude"),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_assistance_points_active_category",
        "verified_assistance_points",
        ["is_active", "category"],
    )
    op.create_index(
        "ix_assistance_points_latitude_longitude",
        "verified_assistance_points",
        ["latitude", "longitude"],
    )

    op.create_table(
        "railway_assistance_records",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("category", sa.String(length=24), nullable=False),
        sa.Column("title", sa.String(length=160), nullable=False),
        sa.Column("description", sa.String(length=1000), nullable=False),
        sa.Column("station_name", sa.String(length=160), nullable=True),
        sa.Column("phone", sa.String(length=32), nullable=True),
        sa.Column("contact_url", sa.String(length=500), nullable=True),
        sa.Column("availability", sa.String(length=160), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("created_by_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("updated_by_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "category IN ('emergency', 'station_help', 'accessibility', 'security', 'other')",
            name="ck_railway_assistance_category",
        ),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_railway_assistance_active_station",
        "railway_assistance_records",
        ["is_active", "station_name"],
    )

    op.create_table(
        "push_device_tokens",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("expo_push_token", sa.String(length=256), nullable=False),
        sa.Column("platform", sa.String(length=16), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("expo_push_token", name="uq_push_device_tokens_expo_token"),
        sa.CheckConstraint("platform IN ('ios', 'android')", name="ck_push_device_tokens_platform"),
    )
    op.create_index(
        "ix_push_device_tokens_user_active",
        "push_device_tokens",
        ["user_id", "is_active"],
    )

    op.create_table(
        "user_notifications",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("title", sa.String(length=160), nullable=False),
        sa.Column("body", sa.String(length=500), nullable=False),
        sa.Column(
            "data",
            sa.JSON().with_variant(postgresql.JSONB(), "postgresql"),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("push_status", sa.String(length=16), server_default="pending", nullable=False),
        sa.Column("push_attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("next_push_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("receipt_attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("receipt_requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_receipt_check_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "push_ticket_ids",
            sa.JSON().with_variant(postgresql.JSONB(), "postgresql"),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "push_ticket_devices",
            sa.JSON().with_variant(postgresql.JSONB(), "postgresql"),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("last_push_error", sa.String(length=500), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "push_status IN ('pending', 'processing', 'accepted', 'receipt_ok', 'failed', 'no_device', 'unknown')",
            name="ck_user_notifications_push_status",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_user_notifications_user_created",
        "user_notifications",
        ["user_id", "created_at"],
    )
    op.create_index(
        "ix_user_notifications_push_queue",
        "user_notifications",
        ["push_status", "next_push_attempt_at"],
    )
    op.create_index(
        "ix_user_notifications_receipt_queue",
        "user_notifications",
        ["push_status", "next_receipt_check_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_user_notifications_receipt_queue", table_name="user_notifications")
    op.drop_index("ix_user_notifications_push_queue", table_name="user_notifications")
    op.drop_index("ix_user_notifications_user_created", table_name="user_notifications")
    op.drop_table("user_notifications")
    op.drop_index("ix_push_device_tokens_user_active", table_name="push_device_tokens")
    op.drop_table("push_device_tokens")
    op.drop_index("ix_railway_assistance_active_station", table_name="railway_assistance_records")
    op.drop_table("railway_assistance_records")
    op.drop_index("ix_assistance_points_latitude_longitude", table_name="verified_assistance_points")
    op.drop_index("ix_assistance_points_active_category", table_name="verified_assistance_points")
    op.drop_table("verified_assistance_points")
    op.drop_index("ix_safety_report_images_report", table_name="community_safety_report_images")
    op.drop_table("community_safety_report_images")
    op.drop_index("ix_community_safety_reports_duplicate", table_name="community_safety_reports")
    op.drop_constraint(
        "fk_community_safety_reports_duplicate_of",
        "community_safety_reports",
        type_="foreignkey",
    )
    op.drop_column("community_safety_reports", "duplicate_of_id")
    op.drop_constraint(
        "ck_community_safety_reports_status",
        "community_safety_reports",
        type_="check",
    )
    op.create_check_constraint(
        "ck_community_safety_reports_status",
        "community_safety_reports",
        "status IN ('pending', 'verified', 'rejected')",
    )
    op.drop_constraint(
        "fk_safety_alerts_admin_reviewed_by",
        "safety_alerts",
        type_="foreignkey",
    )
    op.drop_constraint(
        "ck_safety_alerts_admin_status",
        "safety_alerts",
        type_="check",
    )
    op.drop_column("safety_alerts", "admin_reviewed_at")
    op.drop_column("safety_alerts", "admin_reviewed_by_id")
    op.drop_column("safety_alerts", "admin_note")
    op.drop_column("safety_alerts", "admin_status")
    op.drop_constraint("ck_users_role", "users", type_="check")
    op.drop_column("users", "is_active")
    op.drop_column("users", "role")
