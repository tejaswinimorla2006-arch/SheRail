import asyncio
import logging
import math
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import httpx
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import SessionFactory
from app.models import (
    EmergencyContact,
    Journey,
    JourneyEvent,
    JourneyLocation,
    SafetyAlert,
    SafetyAlertDelivery,
    SafetyEvent,
    User,
)
from app.notification_delivery import enqueue_notification
from app.safety_buddy_alerts import (
    broadcast_safety_buddy_alerts,
    create_safety_buddy_alerts,
)

logger = logging.getLogger(__name__)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def distance_m(latitude_a: float, longitude_a: float, latitude_b: float, longitude_b: float) -> float:
    earth_radius_m = 6_371_000
    lat_a = math.radians(latitude_a)
    lat_b = math.radians(latitude_b)
    delta_lat = lat_b - lat_a
    delta_lon = math.radians(longitude_b - longitude_a)
    value = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat_a) * math.cos(lat_b) * math.sin(delta_lon / 2) ** 2
    )
    return 2 * earth_radius_m * math.atan2(math.sqrt(value), math.sqrt(1 - value))


def distance_from_route_m(latitude: float, longitude: float, route: list[dict]) -> float:
    lat_scale = 111_320
    lon_scale = lat_scale * math.cos(math.radians(latitude))
    px, py = 0.0, 0.0
    points = [
        ((point["longitude"] - longitude) * lon_scale,
         (point["latitude"] - latitude) * lat_scale)
        for point in route
    ]
    minimum = math.inf
    for (ax, ay), (bx, by) in zip(points, points[1:]):
        dx, dy = bx - ax, by - ay
        length_squared = dx * dx + dy * dy
        fraction = 0 if length_squared == 0 else max(
            0, min(1, -(ax * dx + ay * dy) / length_squared)
        )
        nearest_x = ax + fraction * dx
        nearest_y = ay + fraction * dy
        minimum = min(minimum, math.hypot(px - nearest_x, py - nearest_y))
    return minimum


async def add_pending_safety_event(
    db: AsyncSession,
    journey: Journey,
    event_type: str,
    dedupe_key: str,
    details: dict,
    location: JourneyLocation | None,
) -> SafetyEvent:
    event = SafetyEvent(
        user_id=journey.user_id,
        journey_id=journey.id,
        event_type=event_type,
        status="pending_confirmation",
        details=details,
        latitude=location.latitude if location else None,
        longitude=location.longitude if location else None,
        location_captured_at=location.captured_at if location else None,
        dedupe_key=dedupe_key,
        occurred_at=datetime.now(UTC),
    )
    db.add(event)
    db.add(JourneyEvent(journey_id=journey.id, event_type=f"{event_type}_detected"))
    await db.flush()
    enqueue_notification(
        db,
        journey.user_id,
        "safety_event",
        "Safety check-in needed",
        "Please confirm you are safe. Emergency contacts are not notified unless you approve escalation.",
        {"screen": "Notifications", "safety_event_id": str(event.id)},
    )
    return event


async def evaluate_location_safety(
    db: AsyncSession,
    journey: Journey,
    location: JourneyLocation,
    previous: JourneyLocation | None,
) -> list[SafetyEvent]:
    events = []
    if (
        not journey.safety_monitoring_consent
        or journey.status != "active"
        or not journey.location_recording_enabled
        or (location.accuracy_m is not None and location.accuracy_m > 100)
    ):
        return events

    now = datetime.now(UTC)
    if journey.long_stop_enabled:
        if previous is None:
            journey.stationary_since = location.captured_at
        elif distance_m(
            previous.latitude,
            previous.longitude,
            location.latitude,
            location.longitude,
        ) <= journey.stop_radius_m:
            if journey.stationary_since is None:
                journey.stationary_since = previous.captured_at
        else:
            journey.stationary_since = None
            journey.long_stop_alerted_at = None

    if journey.route_deviation_enabled and len(journey.expected_route) >= 2:
        deviation_m = distance_from_route_m(
            location.latitude,
            location.longitude,
            journey.expected_route,
        )
        if deviation_m > journey.route_deviation_threshold_m and not journey.deviation_active:
            journey.deviation_active = True
            journey.deviation_started_at = now
            event = await add_pending_safety_event(
                db,
                journey,
                "route_deviation",
                f"route-deviation:{journey.id}:{now.isoformat()}",
                {
                    "distance_from_route_m": round(deviation_m, 1),
                    "threshold_m": journey.route_deviation_threshold_m,
                },
                location,
            )
            events.append(event)
        elif deviation_m <= journey.route_deviation_threshold_m and journey.deviation_active:
            journey.deviation_active = False
            journey.deviation_started_at = None
            db.add(JourneyEvent(journey_id=journey.id, event_type="route_deviation_cleared"))
    return events


async def notify_journey_owner(
    journey_id: UUID,
    owner_id: UUID,
    event: SafetyEvent,
) -> None:
    from app.live import connection_manager

    await connection_manager.broadcast(
        journey_id,
        {
            "type": "safety_event",
            "event": {
                "id": str(event.id),
                "event_type": event.event_type,
                "details": event.details,
                "occurred_at": event.occurred_at.isoformat(),
            },
        },
        journey_owner_id=owner_id,
        recipient_ids=set(),
    )


def journey_snapshot(journey: Journey | None) -> dict[str, str | None]:
    if journey is None:
        return {}
    return {
        "transport_mode": journey.transport_mode,
        "origin": journey.origin,
        "destination": journey.destination,
        "status": journey.status,
        "started_at": journey.started_at.isoformat() if journey.started_at else None,
        "transport_details": ", ".join(
            f"{key}: {value}" for key, value in journey.transport_details.items()
        ) or None,
    }


async def create_safety_alert(
    db: AsyncSession,
    user: User,
    alert_type: str,
    description: str,
    trigger_key: str,
    journey: Journey | None = None,
    safety_event: SafetyEvent | None = None,
    latitude: float | None = None,
    longitude: float | None = None,
    location_captured_at: datetime | None = None,
) -> SafetyAlert:
    alert = SafetyAlert(
        user_id=user.id,
        journey_id=journey.id if journey else None,
        safety_event_id=safety_event.id if safety_event else None,
        alert_type=alert_type,
        trigger_key=trigger_key,
        description=description,
        journey_snapshot={
            **journey_snapshot(journey),
            "traveler_name": user.name,
        },
        latitude=latitude,
        longitude=longitude,
        location_captured_at=location_captured_at,
        status="pending",
    )
    db.add(alert)
    await db.flush()
    enqueue_notification(
        db,
        user.id,
        "safety_alert",
        "Safety alert created",
        "Your safety alert is saved. Check its status in SheRail.",
        {"screen": "Notifications", "safety_alert_id": str(alert.id)},
    )
    if alert_type == "sos":
        admin_ids = await db.scalars(
            select(User.id).where(User.role == "admin", User.is_active.is_(True))
        )
        for admin_id in admin_ids.all():
            enqueue_notification(
                db,
                admin_id,
                "admin_sos_alert",
                "New SOS alert",
                "An SOS alert needs administrator review.",
                {"screen": "Notifications", "safety_alert_id": str(alert.id)},
            )

    contacts_result = await db.execute(
        select(EmergencyContact)
        .where(EmergencyContact.user_id == user.id)
        .order_by(EmergencyContact.created_at, EmergencyContact.id)
    )
    contacts = list(contacts_result.scalars().all())
    if not contacts:
        alert.status = "failed"
        alert.description = f"{description} No emergency contacts are registered."
        return alert

    for contact in contacts:
        db.add(
            SafetyAlertDelivery(
                alert_id=alert.id,
                contact_id=contact.id,
                contact_name=contact.name,
                phone=contact.phone,
                message_type="initial",
                status="pending",
            )
        )
    return alert


def format_alert_message(alert: SafetyAlert, delivery: SafetyAlertDelivery) -> str:
    if delivery.message_type == "cancellation":
        return (
            f"SheRail update: {alert.description} was cancelled by the traveler at "
            f"{datetime.now(UTC).isoformat()}. No further assistance is needed."
        )

    message = (
        f"SheRail {alert.alert_type.replace('_', ' ').upper()} for "
        f"{alert.journey_snapshot.get('traveler_name', 'the traveler')}. "
        f"{alert.description} Time: {alert.created_at.isoformat()}."
    )
    snapshot = alert.journey_snapshot
    if snapshot:
        journey = " ".join(
            value for value in (
                snapshot.get("transport_mode"),
                f"from {snapshot['origin']}" if snapshot.get("origin") else None,
                f"to {snapshot['destination']}" if snapshot.get("destination") else None,
                snapshot.get("transport_details"),
            ) if value
        )
        if journey:
            message += f" Journey: {journey}."
    if alert.latitude is not None and alert.longitude is not None:
        message += (
            f" Location recorded {alert.location_captured_at.isoformat() if alert.location_captured_at else ''}: "
            f"https://maps.google.com/?q={alert.latitude},{alert.longitude}"
        )
    return message


def sms_provider_configured() -> bool:
    settings = get_settings()
    return bool(
        settings.twilio_account_sid
        and settings.twilio_auth_token
        and settings.twilio_auth_token.get_secret_value()
        and settings.twilio_from_number
    )


async def refresh_alert_status(db: AsyncSession, alert_id: UUID) -> None:
    alert = await db.get(SafetyAlert, alert_id)
    if alert is None or alert.status == "cancelled":
        return
    result = await db.execute(
        select(SafetyAlertDelivery.status).where(
            SafetyAlertDelivery.alert_id == alert_id,
            SafetyAlertDelivery.message_type == "initial",
        )
    )
    statuses = list(result.scalars().all())
    if not statuses:
        alert.status = "failed"
    elif any(value in ("pending", "sending") for value in statuses):
        alert.status = "pending"
    elif all(value == "delivered" for value in statuses):
        alert.status = "delivered"
    elif all(value == "unconfigured" for value in statuses):
        alert.status = "unconfigured"
    elif any(value == "unknown" for value in statuses):
        alert.status = (
            "partial"
            if any(value in ("queued", "sent", "delivered") for value in statuses)
            else "unknown"
        )
    elif any(value in ("queued", "sent", "delivered") for value in statuses):
        alert.status = "partial" if any(value in ("failed", "unconfigured") for value in statuses) else "queued"
    else:
        alert.status = "failed"


async def dispatch_delivery(delivery_id: UUID) -> None:
    async with SessionFactory() as db:
        delivery = await db.scalar(
            select(SafetyAlertDelivery)
            .where(
                SafetyAlertDelivery.id == delivery_id,
                SafetyAlertDelivery.status == "pending",
            )
            .with_for_update(skip_locked=True)
        )
        if delivery is None:
            return
        alert = await db.get(SafetyAlert, delivery.alert_id)
        if alert is None:
            delivery.status = "failed"
            delivery.last_error = "The alert record is unavailable."
            await db.commit()
            return
        if alert.status == "cancelled" and delivery.message_type == "initial":
            delivery.status = "cancelled"
            await db.commit()
            return
        delivery.status = "sending"
        delivery.attempt_count += 1
        delivery.last_attempt_at = datetime.now(UTC)
        await db.commit()
        settings = get_settings()
        account_sid = settings.twilio_account_sid
        token = settings.twilio_auth_token
        from_number = settings.twilio_from_number
        message_body = format_alert_message(alert, delivery)

    if not sms_provider_configured():
        await set_delivery_result(
            delivery_id,
            "unconfigured",
            "SMS delivery is not configured. Set the Twilio environment variables.",
        )
        return

    settings = get_settings()
    url = f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Messages.json"
    form = {"From": from_number, "To": delivery.phone, "Body": message_body}
    if settings.public_api_base_url:
        form["StatusCallback"] = (
            f"{settings.public_api_base_url}/api/v1/webhooks/twilio/sms-status"
            f"?delivery_id={delivery_id}"
        )

    try:
        async with httpx.AsyncClient(timeout=12) as client:
            response = await client.post(
                url,
                data=form,
                auth=(account_sid, token.get_secret_value()),
            )
        if response.is_success:
            try:
                payload = response.json()
            except ValueError:
                await set_delivery_result(
                    delivery_id,
                    "failed",
                    "The SMS provider returned an unreadable response.",
                )
                return
            provider_message_id = payload.get("sid")
            if not isinstance(provider_message_id, str):
                await set_delivery_result(
                    delivery_id,
                    "failed",
                    "The SMS provider accepted no message identifier; delivery cannot be tracked.",
                )
                return
            provider_status = payload.get("status", "queued")
            delivery_status = "delivered" if provider_status == "delivered" else "queued"
            await set_delivery_result(
                delivery_id,
                delivery_status,
                provider_message_id=provider_message_id,
            )
        else:
            await set_delivery_result(
                delivery_id,
                "failed",
                f"SMS provider rejected the message (HTTP {response.status_code}).",
            )
            logger.warning(
                "SMS delivery %s failed with provider HTTP %s",
                delivery_id,
                response.status_code,
            )
    except httpx.HTTPError as error:
        await set_delivery_result(
            delivery_id,
            "failed",
            f"Could not reach the SMS provider: {type(error).__name__}.",
        )
        logger.warning("SMS delivery %s could not reach its provider", delivery_id)


async def set_delivery_result(
    delivery_id: UUID,
    delivery_status: str,
    error: str | None = None,
    provider_message_id: str | None = None,
) -> None:
    async with SessionFactory() as db:
        delivery = await db.get(SafetyAlertDelivery, delivery_id)
        if delivery is None:
            return
        delivery.status = delivery_status
        delivery.last_error = error
        if provider_message_id:
            delivery.provider_message_id = provider_message_id
        alert_id = delivery.alert_id
        await refresh_alert_status(db, alert_id)
        await db.commit()


async def dispatch_pending_deliveries(limit: int = 50) -> None:
    async with SessionFactory() as db:
        result = await db.execute(
            select(SafetyAlertDelivery.id)
            .where(SafetyAlertDelivery.status == "pending")
            .order_by(SafetyAlertDelivery.created_at)
            .limit(limit)
        )
        delivery_ids = list(result.scalars().all())
    for delivery_id in delivery_ids:
        await dispatch_delivery(delivery_id)


async def mark_stale_deliveries_unknown() -> None:
    cutoff = datetime.now(UTC) - timedelta(minutes=2)
    async with SessionFactory() as db:
        result = await db.execute(
            select(SafetyAlertDelivery)
            .where(
                SafetyAlertDelivery.status == "sending",
                SafetyAlertDelivery.last_attempt_at < cutoff,
            )
            .with_for_update(skip_locked=True)
            .limit(100)
        )
        deliveries = list(result.scalars().all())
        alert_ids = set()
        for delivery in deliveries:
            delivery.status = "unknown"
            delivery.last_error = (
                "The provider response was not recorded; delivery outcome is unknown. "
                "Retrying may send a duplicate."
            )
            alert_ids.add(delivery.alert_id)
        for alert_id in alert_ids:
            await refresh_alert_status(db, alert_id)
        await db.commit()


async def process_missed_checkins() -> None:
    now = datetime.now(UTC)
    async with SessionFactory() as db:
        result = await db.execute(
            select(Journey.id)
            .where(
                Journey.status == "active",
                Journey.safety_monitoring_consent.is_(True),
                Journey.checkin_interval_minutes.is_not(None),
                Journey.checkin_due_at <= now,
            )
            .order_by(Journey.checkin_due_at)
            .limit(100)
        )
        journey_ids = list(result.scalars().all())

    for journey_id in journey_ids:
        async with SessionFactory() as db:
            journey = await db.scalar(
                select(Journey)
                .where(Journey.id == journey_id)
                .with_for_update(skip_locked=True)
            )
            due_at = _as_utc(journey.checkin_due_at) if journey and journey.checkin_due_at else None
            if (
                journey is None
                or journey.status != "active"
                or not journey.safety_monitoring_consent
                or due_at is None
                or due_at + timedelta(minutes=journey.checkin_grace_minutes) > now
            ):
                continue

            dedupe_key = f"missed-checkin:{journey.id}:{due_at.isoformat()}"
            existing = await db.scalar(
                select(SafetyEvent.id).where(SafetyEvent.dedupe_key == dedupe_key)
            )
            if existing is not None:
                continue

            user = await db.get(User, journey.user_id)
            if user is None:
                continue
            event = SafetyEvent(
                user_id=user.id,
                journey_id=journey.id,
                event_type="missed_checkin",
                status="escalated",
                details={
                    "interval_minutes": journey.checkin_interval_minutes,
                    "grace_minutes": journey.checkin_grace_minutes,
                },
                dedupe_key=dedupe_key,
                occurred_at=now,
            )
            db.add(event)
            db.add(JourneyEvent(journey_id=journey.id, event_type="checkin_missed"))
            await db.flush()
            latest = await db.scalar(
                select(JourneyLocation)
                .where(JourneyLocation.journey_id == journey.id)
                .order_by(JourneyLocation.captured_at.desc())
                .limit(1)
            )
            if latest:
                event.latitude = latest.latitude
                event.longitude = latest.longitude
                event.location_captured_at = latest.captured_at
            alert = await create_safety_alert(
                db,
                user,
                "missed_checkin",
                "A scheduled safety check-in was missed.",
                dedupe_key,
                journey,
                event,
                latest.latitude if latest else None,
                latest.longitude if latest else None,
                latest.captured_at if latest else None,
            )
            buddy_alerts = await create_safety_buddy_alerts(
                db,
                journey,
                "missed_checkin",
                "A scheduled safety check-in was missed.",
                f"missed-checkin:{event.id}",
                safety_alert_id=alert.id,
                latitude=latest.latitude if latest else None,
                longitude=latest.longitude if latest else None,
                location_captured_at=latest.captured_at if latest else None,
            )
            journey.checkin_due_at = None
            await db.commit()
            await broadcast_safety_buddy_alerts(journey.id, buddy_alerts)
            await notify_journey_owner(
                journey.id,
                user.id,
                event,
            )


async def process_long_stops() -> None:
    now = datetime.now(UTC)
    async with SessionFactory() as db:
        result = await db.execute(
            select(Journey.id)
            .where(
                Journey.status == "active",
                Journey.location_recording_enabled.is_(True),
                Journey.safety_monitoring_consent.is_(True),
                Journey.long_stop_enabled.is_(True),
                Journey.stationary_since.is_not(None),
                Journey.long_stop_alerted_at.is_(None),
            )
            .limit(100)
        )
        journey_ids = list(result.scalars().all())

    for journey_id in journey_ids:
        async with SessionFactory() as db:
            journey = await db.scalar(
                select(Journey)
                .where(Journey.id == journey_id)
                .with_for_update(skip_locked=True)
            )
            if (
                journey is None
                or journey.status != "active"
                or not journey.location_recording_enabled
                or not journey.safety_monitoring_consent
                or not journey.long_stop_enabled
                or journey.stationary_since is None
                or journey.long_stop_alerted_at is not None
                or journey.stationary_since + timedelta(minutes=journey.long_stop_minutes) > now
            ):
                continue
            location = await db.scalar(
                select(JourneyLocation)
                .where(JourneyLocation.journey_id == journey.id)
                .order_by(JourneyLocation.captured_at.desc())
                .limit(1)
            )
            event = await add_pending_safety_event(
                db,
                journey,
                "long_stop",
                f"long-stop:{journey.id}:{journey.stationary_since.isoformat()}",
                {"duration_minutes": journey.long_stop_minutes},
                location,
            )
            journey.long_stop_alerted_at = now
            await db.commit()
            await notify_journey_owner(journey.id, journey.user_id, event)


async def safety_monitor_worker() -> None:
    while True:
        try:
            await process_missed_checkins()
            await process_long_stops()
            await mark_stale_deliveries_unknown()
            await dispatch_pending_deliveries()
        except SQLAlchemyError:
            logger.exception("Safety monitoring cycle failed")
        await asyncio.sleep(10)
