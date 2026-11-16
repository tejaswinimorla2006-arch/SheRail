import re
from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)


Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
Password = Annotated[str, StringConstraints(min_length=10, max_length=128)]


class RegisterRequest(BaseModel):
    name: Name
    email: EmailStr
    password: Password

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: EmailStr) -> str:
        return str(value).strip().lower()


class LoginRequest(BaseModel):
    email: EmailStr
    password: Annotated[str, StringConstraints(min_length=1, max_length=128)]

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: EmailStr) -> str:
        return str(value).strip().lower()


class UserProfileUpdate(BaseModel):
    name: Name | None = None
    email: EmailStr | None = None

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: EmailStr | None) -> str | None:
        return str(value).strip().lower() if value is not None else None

    @model_validator(mode="after")
    def require_changes(self) -> "UserProfileUpdate":
        if not self.model_fields_set:
            raise ValueError("At least one profile field must be provided")
        if "name" in self.model_fields_set and self.name is None:
            raise ValueError("Name cannot be null")
        if "email" in self.model_fields_set and self.email is None:
            raise ValueError("Email cannot be null")
        return self


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    email: EmailStr
    created_at: datetime


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserRead


class EmergencyContactCreate(BaseModel):
    name: Name
    phone: Annotated[str, StringConstraints(strip_whitespace=True, min_length=7, max_length=32)]
    relationship: Annotated[str, StringConstraints(strip_whitespace=True, max_length=80)] | None = None
    is_primary: bool = False

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, value: str) -> str:
        if not re.fullmatch(r"\+?[\d\s().-]+", value):
            raise ValueError("Enter a valid phone number")
        digits = re.sub(r"\D", "", value)
        if not 7 <= len(digits) <= 15:
            raise ValueError("Phone number must contain 7 to 15 digits")
        return value


class EmergencyContactUpdate(BaseModel):
    name: Name | None = None
    phone: Annotated[str, StringConstraints(strip_whitespace=True, min_length=7, max_length=32)] | None = None
    relationship: Annotated[str, StringConstraints(strip_whitespace=True, max_length=80)] | None = None
    is_primary: bool | None = None

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return EmergencyContactCreate.validate_phone(value)

    @model_validator(mode="after")
    def require_changes(self) -> "EmergencyContactUpdate":
        if not self.model_fields_set:
            raise ValueError("At least one contact field must be provided")
        if "name" in self.model_fields_set and self.name is None:
            raise ValueError("Name cannot be null")
        if "phone" in self.model_fields_set and self.phone is None:
            raise ValueError("Phone cannot be null")
        if "is_primary" in self.model_fields_set and self.is_primary is None:
            raise ValueError("is_primary cannot be null")
        return self


class EmergencyContactRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    phone: str
    relationship: str | None = Field(
        default=None,
        validation_alias=AliasChoices("relationship_name", "relationship"),
    )
    is_primary: bool
    created_at: datetime
    updated_at: datetime


class TransportMode(str, Enum):
    WALKING = "walking"
    BUS = "bus"
    TRAIN = "train"
    METRO = "metro"
    CAB = "cab"


class JourneyStatus(str, Enum):
    PLANNED = "planned"
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"


class JourneyCreate(BaseModel):
    transport_mode: TransportMode
    origin: Annotated[str, StringConstraints(strip_whitespace=True, max_length=160)] | None = None
    destination: Annotated[str, StringConstraints(strip_whitespace=True, max_length=160)] | None = None
    transport_details: dict[str, str] = Field(default_factory=dict)

    @field_validator("transport_details")
    @classmethod
    def validate_transport_details(cls, value: dict[str, str]) -> dict[str, str]:
        if len(value) > 10 or any(not key.strip() or len(key) > 40 or len(detail) > 160 for key, detail in value.items()):
            raise ValueError("Transport details contain an invalid field or value")
        return value


class JourneyLocationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    latitude: float
    longitude: float
    accuracy_m: float | None
    captured_at: datetime
    received_at: datetime


class JourneyEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    event_type: str
    occurred_at: datetime


class RouteCoordinate(BaseModel):
    latitude: Annotated[float, Field(ge=-90, le=90)]
    longitude: Annotated[float, Field(ge=-180, le=180)]


class JourneySummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    transport_mode: TransportMode
    status: JourneyStatus
    origin: str | None
    destination: str | None
    transport_details: dict[str, str]
    location_recording_enabled: bool
    location_consent_at: datetime | None
    sharing_enabled: bool
    safety_monitoring_consent: bool
    checkin_interval_minutes: int | None
    checkin_grace_minutes: int
    checkin_due_at: datetime | None
    route_deviation_enabled: bool
    route_deviation_threshold_m: float
    expected_route: list[RouteCoordinate]
    long_stop_enabled: bool
    long_stop_minutes: int
    stop_radius_m: float
    created_at: datetime
    started_at: datetime | None
    paused_at: datetime | None
    ended_at: datetime | None


class JourneyShareRead(BaseModel):
    id: UUID
    recipient_user_id: UUID
    recipient_name: str
    recipient_email: EmailStr
    created_at: datetime


class JourneyDetail(JourneySummary):
    locations: list[JourneyLocationRead]
    events: list[JourneyEventRead]
    shares: list[JourneyShareRead] = Field(default_factory=list)


class LocationConsentRequest(BaseModel):
    consent: bool


class JourneyShareCreate(BaseModel):
    recipient_email: EmailStr

    @field_validator("recipient_email")
    @classmethod
    def normalize_email(cls, value: EmailStr) -> str:
        return str(value).strip().lower()


class JourneySharedSummary(JourneySummary):
    owner_name: str
    latest_location: JourneyLocationRead | None = None
    safety_monitoring_consent: bool = Field(exclude=True)
    checkin_interval_minutes: int | None = Field(exclude=True)
    checkin_grace_minutes: int = Field(exclude=True)
    checkin_due_at: datetime | None = Field(exclude=True)
    route_deviation_enabled: bool = Field(exclude=True)
    route_deviation_threshold_m: float = Field(exclude=True)
    expected_route: list[RouteCoordinate] = Field(exclude=True)
    long_stop_enabled: bool = Field(exclude=True)
    long_stop_minutes: int = Field(exclude=True)
    stop_radius_m: float = Field(exclude=True)


class ExpectedRouteUpdate(BaseModel):
    points: list[RouteCoordinate] = Field(max_length=100)

    @model_validator(mode="after")
    def require_route_points(self) -> "ExpectedRouteUpdate":
        if self.points and len(self.points) < 2:
            raise ValueError("An expected route needs at least two waypoints")
        return self


class JourneySafetySettingsUpdate(BaseModel):
    consent: bool
    checkin_interval_minutes: Annotated[int, Field(ge=1, le=240)] | None
    checkin_grace_minutes: Annotated[int, Field(ge=1, le=30)]
    route_deviation_enabled: bool
    route_deviation_threshold_m: Annotated[float, Field(ge=50, le=5000)]
    long_stop_enabled: bool
    long_stop_minutes: Annotated[int, Field(ge=2, le=180)]
    stop_radius_m: Annotated[float, Field(ge=10, le=500)]


class SafetyEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    journey_id: UUID | None
    event_type: str
    status: str
    details: dict[str, str | float | int | bool | None]
    latitude: float | None
    longitude: float | None
    location_captured_at: datetime | None
    occurred_at: datetime
    resolved_at: datetime | None


class SOSAlertCreate(BaseModel):
    share_location: bool
    latitude: Annotated[float, Field(ge=-90, le=90)] | None = None
    longitude: Annotated[float, Field(ge=-180, le=180)] | None = None
    location_captured_at: datetime | None = None
    journey_id: UUID | None = None
    request_id: UUID | None = None

    @model_validator(mode="after")
    def require_consented_location(self) -> "SOSAlertCreate":
        has_location = (
            self.latitude is not None
            and self.longitude is not None
            and self.location_captured_at is not None
        )
        if self.share_location and not has_location:
            raise ValueError("A current location and timestamp are required when sharing location")
        if not self.share_location and any(
            value is not None
            for value in (self.latitude, self.longitude, self.location_captured_at)
        ):
            raise ValueError("Location data cannot be sent without location consent")
        if self.location_captured_at is not None and self.location_captured_at.tzinfo is None:
            raise ValueError("location_captured_at must include a timezone")
        return self


class SafetyAlertDeliveryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    contact_name: str
    phone: str
    message_type: str
    status: str
    provider_message_id: str | None
    last_error: str | None
    attempt_count: int
    created_at: datetime
    last_attempt_at: datetime | None
    updated_at: datetime


class SafetyAlertRead(BaseModel):
    id: UUID
    journey_id: UUID | None
    safety_event_id: UUID | None
    alert_type: str
    status: str
    description: str
    journey_snapshot: dict[str, str | None]
    latitude: float | None
    longitude: float | None
    location_captured_at: datetime | None
    created_at: datetime
    cancelled_at: datetime | None
    deliveries: list[SafetyAlertDeliveryRead]


class WebSocketLocationUpdate(BaseModel):
    latitude: Annotated[float, Field(ge=-90, le=90)]
    longitude: Annotated[float, Field(ge=-180, le=180)]
    accuracy_m: Annotated[float, Field(ge=0, le=100000)] | None = None
    captured_at: datetime

    @field_validator("captured_at")
    @classmethod
    def normalize_captured_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("captured_at must include a timezone")
        value = value.astimezone(UTC)
        now = datetime.now(UTC)
        if value > now + timedelta(minutes=5):
            raise ValueError("captured_at cannot be in the future")
        if value < now - timedelta(hours=1):
            raise ValueError("captured_at is too old for a live location update")
        return value


class SafetyBuddyInviteCreate(BaseModel):
    email: EmailStr

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: EmailStr) -> str:
        return str(value).strip().lower()


class SafetyBuddyInviteResponse(BaseModel):
    accept: bool


class SafetyBuddyJourneyShareRequest(BaseModel):
    location_consent: bool


class SafetyBuddyLinkRead(BaseModel):
    id: UUID
    peer_user_id: UUID
    peer_name: str
    peer_email: EmailStr
    status: str
    direction: str
    created_at: datetime
    responded_at: datetime | None


class SafetyBuddyOverview(BaseModel):
    sent: list[SafetyBuddyLinkRead]
    received: list[SafetyBuddyLinkRead]
    accepted: list[SafetyBuddyLinkRead]


class SafetyBuddyAlertRead(BaseModel):
    id: UUID
    owner_user_id: UUID
    owner_name: str
    journey_id: UUID | None
    safety_alert_id: UUID | None
    alert_type: str
    description: str
    latitude: float | None
    longitude: float | None
    location_captured_at: datetime | None
    created_at: datetime
    read_at: datetime | None


class LocationSearchRequest(BaseModel):
    latitude: Annotated[float, Field(ge=-90, le=90)]
    longitude: Annotated[float, Field(ge=-180, le=180)]
    radius_m: Annotated[int, Field(ge=100, le=10000)] = 5000
    location_consent: bool


class NearbyPlaceRead(BaseModel):
    id: str
    name: str
    category: str
    latitude: float
    longitude: float
    distance_m: int
    address: str | None
    osm_url: str | None = None
    phone: str | None = None
    description: str | None = None
    source: Literal["openstreetmap", "sherail_verified"] = "openstreetmap"


class SafetyReportType(str, Enum):
    HARASSMENT = "harassment"
    THEFT = "theft"
    UNSAFE_AREA = "unsafe_area"
    POOR_LIGHTING = "poor_lighting"
    OTHER = "other"


class CommunitySafetyReportCreate(BaseModel):
    report_type: SafetyReportType
    description: Annotated[str, StringConstraints(strip_whitespace=True, min_length=10, max_length=500)]
    latitude: Annotated[float, Field(ge=-90, le=90)]
    longitude: Annotated[float, Field(ge=-180, le=180)]
    location_consent: bool


class CommunitySafetyReportRead(BaseModel):
    id: UUID
    report_type: SafetyReportType
    description: str
    status: Literal["pending", "under_review", "verified", "rejected", "duplicate"]
    latitude: float
    longitude: float
    duplicate_of_id: UUID | None = None
    image_ids: list[UUID] = Field(default_factory=list)
    distance_m: int | None = None
    created_at: datetime
    verified_at: datetime | None


class CommunitySafetyReportReview(BaseModel):
    status: str
    moderator_note: Annotated[str, StringConstraints(strip_whitespace=True, max_length=300)] | None = None
    duplicate_of_id: UUID | None = None

    @field_validator("status")
    @classmethod
    def validate_status(cls, value: str) -> str:
        if value not in ("pending", "under_review", "verified", "rejected", "duplicate"):
            raise ValueError("Choose a supported report status")
        return value

    @model_validator(mode="after")
    def validate_duplicate(self) -> "CommunitySafetyReportReview":
        if self.status == "duplicate" and self.duplicate_of_id is None:
            raise ValueError("Choose the original report when marking a duplicate")
        if self.status != "duplicate" and self.duplicate_of_id is not None:
            raise ValueError("Only duplicate reports can link to an original report")
        return self


class ModeratorAccessRead(BaseModel):
    can_moderate: bool


class ExpoPushTokenCreate(BaseModel):
    expo_push_token: Annotated[str, StringConstraints(strip_whitespace=True, min_length=20, max_length=256)]
    platform: Literal["ios", "android"]

    @field_validator("expo_push_token")
    @classmethod
    def validate_expo_token(cls, value: str) -> str:
        if not value.startswith(("ExpoPushToken[", "ExponentPushToken[")) or not value.endswith("]"):
            raise ValueError("Register a valid Expo push token")
        return value


class PushDeviceStatusRead(BaseModel):
    enabled: bool


class UserNotificationRead(BaseModel):
    id: UUID
    kind: str
    title: str
    body: str
    data: dict[str, str | int | float | bool | None]
    read_at: datetime | None
    push_status: str
    created_at: datetime


class AdminOverviewRead(BaseModel):
    users: int
    active_users: int
    open_sos_alerts: int
    pending_reports: int
    verified_assistance_points: int
    active_railway_records: int


class AdminUserRead(BaseModel):
    id: UUID
    name: str
    email: EmailStr
    role: str
    is_active: bool
    created_at: datetime


class AdminUserUpdate(BaseModel):
    role: Literal["user", "admin"]
    is_active: bool


class AdminSOSDeliveryRead(BaseModel):
    contact_name: str
    phone: str
    message_type: str
    status: str
    last_error: str | None
    attempt_count: int


class AdminSOSAlertRead(BaseModel):
    id: UUID
    user_id: UUID
    user_name: str
    user_email: EmailStr
    journey_id: UUID | None
    alert_type: str
    status: str
    admin_status: str
    admin_note: str | None
    description: str
    journey_snapshot: dict[str, str | None]
    latitude: float | None
    longitude: float | None
    location_captured_at: datetime | None
    created_at: datetime
    admin_reviewed_at: datetime | None
    deliveries: list[AdminSOSDeliveryRead] = Field(default_factory=list)


class AdminSOSAlertUpdate(BaseModel):
    admin_status: Literal["open", "investigating", "resolved", "dismissed"]
    admin_note: Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)] | None = None


class AdminCommunityReportRead(CommunitySafetyReportRead):
    user_id: UUID
    user_name: str
    user_email: EmailStr
    moderator_note: str | None


class AssistancePointCategory(str, Enum):
    POLICE = "police"
    HOSPITAL = "hospital"
    CLINIC = "clinic"
    SHELTER = "shelter"
    CRISIS_CENTER = "crisis_center"
    ASSISTANCE_POINT = "assistance_point"
    RAILWAY_ASSISTANCE = "railway_assistance"


class AssistancePointCreate(BaseModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=160)]
    category: AssistancePointCategory
    description: Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)] | None = None
    address: Annotated[str, StringConstraints(strip_whitespace=True, max_length=300)] | None = None
    phone: Annotated[str, StringConstraints(strip_whitespace=True, min_length=7, max_length=32)] | None = None
    latitude: Annotated[float, Field(ge=-90, le=90)]
    longitude: Annotated[float, Field(ge=-180, le=180)]
    is_active: bool = True

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, value: str | None) -> str | None:
        if value is not None:
            EmergencyContactCreate.validate_phone(value)
        return value


class AssistancePointUpdate(BaseModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=160)] | None = None
    category: AssistancePointCategory | None = None
    description: Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)] | None = None
    address: Annotated[str, StringConstraints(strip_whitespace=True, max_length=300)] | None = None
    phone: Annotated[str, StringConstraints(strip_whitespace=True, min_length=7, max_length=32)] | None = None
    latitude: Annotated[float, Field(ge=-90, le=90)] | None = None
    longitude: Annotated[float, Field(ge=-180, le=180)] | None = None
    is_active: bool | None = None

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, value: str | None) -> str | None:
        if value is not None:
            EmergencyContactCreate.validate_phone(value)
        return value

    @model_validator(mode="after")
    def require_changes(self) -> "AssistancePointUpdate":
        if not self.model_fields_set:
            raise ValueError("At least one assistance-point field must be provided")
        return self


class AssistancePointRead(BaseModel):
    id: UUID
    name: str
    category: AssistancePointCategory
    description: str | None
    address: str | None
    phone: str | None
    latitude: float
    longitude: float
    is_active: bool
    verified_at: datetime
    created_at: datetime
    updated_at: datetime


class RailwayAssistanceCategory(str, Enum):
    EMERGENCY = "emergency"
    STATION_HELP = "station_help"
    ACCESSIBILITY = "accessibility"
    SECURITY = "security"
    OTHER = "other"


class RailwayAssistanceCreate(BaseModel):
    category: RailwayAssistanceCategory
    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=160)]
    description: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]
    station_name: Annotated[str, StringConstraints(strip_whitespace=True, max_length=160)] | None = None
    phone: Annotated[str, StringConstraints(strip_whitespace=True, min_length=7, max_length=32)] | None = None
    contact_url: Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)] | None = None
    availability: Annotated[str, StringConstraints(strip_whitespace=True, max_length=160)] | None = None
    is_active: bool = True

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, value: str | None) -> str | None:
        if value is not None:
            EmergencyContactCreate.validate_phone(value)
        return value

    @field_validator("contact_url")
    @classmethod
    def validate_contact_url(cls, value: str | None) -> str | None:
        if value is not None and not value.startswith(("https://", "http://")):
            raise ValueError("Contact links must use http or https")
        return value


class RailwayAssistanceUpdate(BaseModel):
    category: RailwayAssistanceCategory | None = None
    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=160)] | None = None
    description: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)] | None = None
    station_name: Annotated[str, StringConstraints(strip_whitespace=True, max_length=160)] | None = None
    phone: Annotated[str, StringConstraints(strip_whitespace=True, min_length=7, max_length=32)] | None = None
    contact_url: Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)] | None = None
    availability: Annotated[str, StringConstraints(strip_whitespace=True, max_length=160)] | None = None
    is_active: bool | None = None

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, value: str | None) -> str | None:
        if value is not None:
            EmergencyContactCreate.validate_phone(value)
        return value

    @field_validator("contact_url")
    @classmethod
    def validate_contact_url(cls, value: str | None) -> str | None:
        if value is not None and not value.startswith(("https://", "http://")):
            raise ValueError("Contact links must use http or https")
        return value

    @model_validator(mode="after")
    def require_changes(self) -> "RailwayAssistanceUpdate":
        if not self.model_fields_set:
            raise ValueError("At least one railway assistance field must be provided")
        return self


class RailwayAssistanceRead(BaseModel):
    id: UUID
    category: RailwayAssistanceCategory
    title: str
    description: str
    station_name: str | None
    phone: str | None
    contact_url: str | None
    availability: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime
