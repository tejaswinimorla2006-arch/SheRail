from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    Index,
    LargeBinary,
    String,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("role IN ('user', 'admin')", name="ck_users_role"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(
        String(16), default="user", server_default="user", nullable=False
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true", nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    emergency_contacts: Mapped[list["EmergencyContact"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    journeys: Mapped[list["Journey"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class EmergencyContact(Base):
    __tablename__ = "emergency_contacts"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    phone: Mapped[str] = mapped_column(String(32), nullable=False)
    relationship_name: Mapped[str | None] = mapped_column("relationship", String(80))
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    user: Mapped[User] = relationship(back_populates="emergency_contacts")


class Journey(Base):
    __tablename__ = "journeys"
    __table_args__ = (
        CheckConstraint(
            "transport_mode IN ('walking', 'bus', 'train', 'metro', 'cab')",
            name="ck_journeys_transport_mode",
        ),
        CheckConstraint(
            "status IN ('planned', 'active', 'paused', 'completed')",
            name="ck_journeys_status",
        ),
        Index("ix_journeys_user_created", "user_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    transport_mode: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="planned", nullable=False)
    origin: Mapped[str | None] = mapped_column(String(160))
    destination: Mapped[str | None] = mapped_column(String(160))
    transport_details: Mapped[dict[str, str]] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"),
        default=dict,
        nullable=False,
    )
    location_recording_enabled: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    location_consent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sharing_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    safety_monitoring_consent: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    checkin_interval_minutes: Mapped[int | None] = mapped_column(Integer)
    checkin_grace_minutes: Mapped[int] = mapped_column(Integer, default=2, nullable=False)
    checkin_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    checkin_consent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    route_deviation_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    route_deviation_threshold_m: Mapped[float] = mapped_column(Float, default=250, nullable=False)
    expected_route: Mapped[list[dict[str, float]]] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"),
        default=list,
        nullable=False,
    )
    deviation_active: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    deviation_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    long_stop_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    long_stop_minutes: Mapped[int] = mapped_column(Integer, default=10, nullable=False)
    stop_radius_m: Mapped[float] = mapped_column(Float, default=50, nullable=False)
    stationary_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    long_stop_alerted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    paused_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship(back_populates="journeys")
    locations: Mapped[list["JourneyLocation"]] = relationship(
        back_populates="journey", cascade="all, delete-orphan"
    )
    events: Mapped[list["JourneyEvent"]] = relationship(
        back_populates="journey", cascade="all, delete-orphan"
    )
    shares: Mapped[list["JourneyShare"]] = relationship(
        back_populates="journey", cascade="all, delete-orphan"
    )


class SafetyEvent(Base):
    __tablename__ = "safety_events"
    __table_args__ = (
        UniqueConstraint("dedupe_key", name="uq_safety_events_dedupe_key"),
        Index("ix_safety_events_user_status", "user_id", "status", "occurred_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    journey_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("journeys.id", ondelete="SET NULL")
    )
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    details: Mapped[dict[str, str | float | int | bool | None]] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"), default=dict, nullable=False
    )
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)
    location_captured_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dedupe_key: Mapped[str] = mapped_column(String(200), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SafetyAlert(Base):
    __tablename__ = "safety_alerts"
    __table_args__ = (
        UniqueConstraint("trigger_key", name="uq_safety_alerts_trigger_key"),
        Index("ix_safety_alerts_user_created", "user_id", "created_at"),
        CheckConstraint(
            "admin_status IN ('open', 'investigating', 'resolved', 'dismissed')",
            name="ck_safety_alerts_admin_status",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    journey_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("journeys.id", ondelete="SET NULL")
    )
    safety_event_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("safety_events.id", ondelete="SET NULL")
    )
    alert_type: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="pending")
    trigger_key: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(String(500), nullable=False)
    journey_snapshot: Mapped[dict[str, str | None]] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"), default=dict, nullable=False
    )
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)
    location_captured_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    admin_status: Mapped[str] = mapped_column(
        String(16), default="open", server_default="open", nullable=False
    )
    admin_note: Mapped[str | None] = mapped_column(String(500))
    admin_reviewed_by_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    admin_reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    deliveries: Mapped[list["SafetyAlertDelivery"]] = relationship(
        back_populates="alert", cascade="all, delete-orphan"
    )


class SafetyAlertDelivery(Base):
    __tablename__ = "safety_alert_deliveries"
    __table_args__ = (
        UniqueConstraint("alert_id", "contact_id", "message_type", name="uq_safety_alert_delivery"),
        Index("ix_safety_alert_deliveries_status", "status", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    alert_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("safety_alerts.id", ondelete="CASCADE"), nullable=False
    )
    contact_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("emergency_contacts.id", ondelete="SET NULL")
    )
    contact_name: Mapped[str] = mapped_column(String(120), nullable=False)
    phone: Mapped[str] = mapped_column(String(32), nullable=False)
    message_type: Mapped[str] = mapped_column(String(16), nullable=False, default="initial")
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="pending")
    provider_message_id: Mapped[str | None] = mapped_column(String(64), unique=True)
    last_error: Mapped[str | None] = mapped_column(String(500))
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    alert: Mapped[SafetyAlert] = relationship(back_populates="deliveries")


class SafetyBuddyLink(Base):
    __tablename__ = "safety_buddy_links"
    __table_args__ = (
        UniqueConstraint("user_one_id", "user_two_id", name="uq_safety_buddy_pair"),
        CheckConstraint("user_one_id <> user_two_id", name="ck_safety_buddy_distinct_users"),
        CheckConstraint(
            "invited_by_id IN (user_one_id, user_two_id)",
            name="ck_safety_buddy_inviter_is_participant",
        ),
        CheckConstraint(
            "status IN ('pending', 'accepted', 'declined')",
            name="ck_safety_buddy_status",
        ),
        Index("ix_safety_buddy_one_status", "user_one_id", "status"),
        Index("ix_safety_buddy_two_status", "user_two_id", "status"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    user_one_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    user_two_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    invited_by_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(16), default="pending", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SafetyBuddyAlert(Base):
    __tablename__ = "safety_buddy_alerts"
    __table_args__ = (
        UniqueConstraint("dedupe_key", name="uq_safety_buddy_alert_dedupe_key"),
        Index("ix_safety_buddy_alerts_recipient", "buddy_user_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    buddy_link_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("safety_buddy_links.id", ondelete="CASCADE"), nullable=False
    )
    owner_user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    buddy_user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    journey_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("journeys.id", ondelete="SET NULL")
    )
    safety_alert_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("safety_alerts.id", ondelete="SET NULL")
    )
    alert_type: Mapped[str] = mapped_column(String(32), nullable=False)
    description: Mapped[str] = mapped_column(String(400), nullable=False)
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)
    location_captured_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dedupe_key: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CommunitySafetyReport(Base):
    __tablename__ = "community_safety_reports"
    __table_args__ = (
        CheckConstraint(
            "report_type IN ('harassment', 'theft', 'unsafe_area', 'poor_lighting', 'other')",
            name="ck_community_safety_reports_type",
        ),
        CheckConstraint(
            "status IN ('pending', 'under_review', 'verified', 'rejected', 'duplicate')",
            name="ck_community_safety_reports_status",
        ),
        CheckConstraint(
            "latitude >= -90 AND latitude <= 90",
            name="ck_community_safety_reports_latitude",
        ),
        CheckConstraint(
            "longitude >= -180 AND longitude <= 180",
            name="ck_community_safety_reports_longitude",
        ),
        Index("ix_community_safety_reports_status_created", "status", "created_at"),
        Index("ix_community_safety_reports_latitude_longitude", "latitude", "longitude"),
        Index("ix_community_safety_reports_duplicate", "duplicate_of_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    report_type: Mapped[str] = mapped_column(String(24), nullable=False)
    description: Mapped[str] = mapped_column(String(500), nullable=False)
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
    location_consented_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="pending", nullable=False)
    moderator_note: Mapped[str | None] = mapped_column(String(300))
    duplicate_of_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("community_safety_reports.id", ondelete="SET NULL")
    )
    verified_by_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    images: Mapped[list["CommunitySafetyReportImage"]] = relationship(
        back_populates="report", cascade="all, delete-orphan", lazy="selectin"
    )


class CommunitySafetyReportImage(Base):
    __tablename__ = "community_safety_report_images"
    __table_args__ = (
        UniqueConstraint("report_id", "sha256", name="uq_safety_report_image_hash"),
        Index("ix_safety_report_images_report", "report_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    report_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("community_safety_reports.id", ondelete="CASCADE"),
        nullable=False,
    )
    media_type: Mapped[str] = mapped_column(String(32), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    content: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    report: Mapped[CommunitySafetyReport] = relationship(back_populates="images")


class VerifiedAssistancePoint(Base):
    __tablename__ = "verified_assistance_points"
    __table_args__ = (
        CheckConstraint(
            "category IN ('police', 'hospital', 'clinic', 'shelter', 'crisis_center', 'assistance_point', 'railway_assistance')",
            name="ck_verified_assistance_points_category",
        ),
        CheckConstraint("latitude >= -90 AND latitude <= 90", name="ck_assistance_points_latitude"),
        CheckConstraint("longitude >= -180 AND longitude <= 180", name="ck_assistance_points_longitude"),
        Index("ix_assistance_points_active_category", "is_active", "category"),
        Index("ix_assistance_points_latitude_longitude", "latitude", "longitude"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500))
    address: Mapped[str | None] = mapped_column(String(300))
    phone: Mapped[str | None] = mapped_column(String(32))
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_by_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    updated_by_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    verified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class RailwayAssistanceRecord(Base):
    __tablename__ = "railway_assistance_records"
    __table_args__ = (
        CheckConstraint(
            "category IN ('emergency', 'station_help', 'accessibility', 'security', 'other')",
            name="ck_railway_assistance_category",
        ),
        Index("ix_railway_assistance_active_station", "is_active", "station_name"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    category: Mapped[str] = mapped_column(String(24), nullable=False)
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str] = mapped_column(String(1000), nullable=False)
    station_name: Mapped[str | None] = mapped_column(String(160))
    phone: Mapped[str | None] = mapped_column(String(32))
    contact_url: Mapped[str | None] = mapped_column(String(500))
    availability: Mapped[str | None] = mapped_column(String(160))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_by_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    updated_by_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class PushDeviceToken(Base):
    __tablename__ = "push_device_tokens"
    __table_args__ = (Index("ix_push_device_tokens_user_active", "user_id", "is_active"),)

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    expo_push_token: Mapped[str] = mapped_column(String(256), unique=True, nullable=False)
    platform: Mapped[str] = mapped_column(String(16), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class UserNotification(Base):
    __tablename__ = "user_notifications"
    __table_args__ = (
        CheckConstraint(
            "push_status IN ('pending', 'processing', 'accepted', 'receipt_ok', 'failed', 'no_device', 'unknown')",
            name="ck_user_notifications_push_status",
        ),
        Index("ix_user_notifications_user_created", "user_id", "created_at"),
        Index("ix_user_notifications_push_queue", "push_status", "next_push_attempt_at"),
        Index("ix_user_notifications_receipt_queue", "push_status", "next_receipt_check_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    body: Mapped[str] = mapped_column(String(500), nullable=False)
    data: Mapped[dict[str, str | int | float | bool | None]] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"), default=dict, nullable=False
    )
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    push_status: Mapped[str] = mapped_column(String(16), default="pending", nullable=False)
    push_attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    next_push_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    receipt_attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    receipt_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_receipt_check_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    push_ticket_ids: Mapped[list[str]] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"), default=list, nullable=False
    )
    push_ticket_devices: Mapped[list[dict[str, str]]] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"), default=list, nullable=False
    )
    last_push_error: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class JourneyLocation(Base):
    __tablename__ = "journey_locations"
    __table_args__ = (
        CheckConstraint("latitude >= -90 AND latitude <= 90", name="ck_journey_locations_latitude"),
        CheckConstraint("longitude >= -180 AND longitude <= 180", name="ck_journey_locations_longitude"),
        Index("ix_journey_locations_route", "journey_id", "captured_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    journey_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("journeys.id", ondelete="CASCADE"),
        nullable=False,
    )
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
    accuracy_m: Mapped[float | None] = mapped_column(Float)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    journey: Mapped[Journey] = relationship(back_populates="locations")


class JourneyEvent(Base):
    __tablename__ = "journey_events"
    __table_args__ = (
        Index("ix_journey_events_timeline", "journey_id", "occurred_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    journey_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("journeys.id", ondelete="CASCADE"),
        nullable=False,
    )
    event_type: Mapped[str] = mapped_column(String(40), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    journey: Mapped[Journey] = relationship(back_populates="events")


class JourneyShare(Base):
    __tablename__ = "journey_shares"
    __table_args__ = (
        UniqueConstraint("journey_id", "recipient_user_id", name="uq_journey_share_recipient"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    journey_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("journeys.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    recipient_user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    journey: Mapped[Journey] = relationship(back_populates="shares")
    recipient: Mapped[User] = relationship(foreign_keys=[recipient_user_id])
