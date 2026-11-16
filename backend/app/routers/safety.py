import base64
import hashlib
import hmac
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qsl
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.dependencies import get_current_user
from app.models import (
    Journey,
    JourneyEvent,
    JourneyLocation,
    SafetyAlert,
    SafetyAlertDelivery,
    SafetyEvent,
    User,
)
from app.safety_buddy_alerts import (
    broadcast_safety_buddy_alerts,
    create_safety_buddy_alerts,
)
from app.safety import create_safety_alert, refresh_alert_status, sms_provider_configured
from app.schemas import (
    SOSAlertCreate,
    SafetyAlertDeliveryRead,
    SafetyAlertRead,
    SafetyEventRead,
)

router = APIRouter(prefix="/safety", tags=["safety monitoring and emergency alerts"])


async def serialize_alert(db: AsyncSession, alert: SafetyAlert) -> SafetyAlertRead:
    result = await db.execute(
        select(SafetyAlertDelivery)
        .where(SafetyAlertDelivery.alert_id == alert.id)
        .order_by(SafetyAlertDelivery.created_at, SafetyAlertDelivery.id)
    )
    return SafetyAlertRead(
        id=alert.id,
        journey_id=alert.journey_id,
        safety_event_id=alert.safety_event_id,
        alert_type=alert.alert_type,
        status=alert.status,
        description=alert.description,
        journey_snapshot=alert.journey_snapshot,
        latitude=alert.latitude,
        longitude=alert.longitude,
        location_captured_at=alert.location_captured_at,
        created_at=alert.created_at,
        cancelled_at=alert.cancelled_at,
        deliveries=[
            SafetyAlertDeliveryRead.model_validate(item)
            for item in result.scalars().all()
        ],
    )


async def get_owned_alert(
    alert_id: UUID,
    user_id: UUID,
    db: AsyncSession,
) -> SafetyAlert:
    result = await db.execute(
        select(SafetyAlert).where(
            SafetyAlert.id == alert_id,
            SafetyAlert.user_id == user_id,
        )
    )
    alert = result.scalar_one_or_none()
    if alert is None:
        raise HTTPException(status_code=404, detail="Safety alert not found")
    return alert


@router.get("/events", response_model=list[SafetyEventRead])
async def list_safety_events(
    pending_only: bool = True,
    limit: int = 50,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[SafetyEvent]:
    statement = select(SafetyEvent).where(SafetyEvent.user_id == user.id)
    if pending_only:
        statement = statement.where(SafetyEvent.status == "pending_confirmation")
    result = await db.execute(
        statement.order_by(SafetyEvent.occurred_at.desc()).limit(min(max(limit, 1), 100))
    )
    return list(result.scalars().all())


@router.post("/events/{event_id}/dismiss", response_model=SafetyEventRead)
async def dismiss_safety_event(
    event_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SafetyEvent:
    event = await db.scalar(
        select(SafetyEvent)
        .where(SafetyEvent.id == event_id, SafetyEvent.user_id == user.id)
        .with_for_update()
    )
    if event is None:
        raise HTTPException(status_code=404, detail="Safety event not found")
    if event.status != "pending_confirmation":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This safety event has already been resolved",
        )
    event.status = "dismissed"
    event.resolved_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(event)
    return event


@router.post("/events/{event_id}/confirm", response_model=SafetyAlertRead)
async def confirm_safety_event(
    event_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SafetyAlertRead:
    event = await db.scalar(
        select(SafetyEvent)
        .where(SafetyEvent.id == event_id, SafetyEvent.user_id == user.id)
        .with_for_update()
    )
    if event is None:
        raise HTTPException(status_code=404, detail="Safety event not found")
    if event.status != "pending_confirmation":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This safety event has already been resolved",
        )
    journey = await db.get(Journey, event.journey_id) if event.journey_id else None
    latest = await db.scalar(
        select(JourneyLocation)
        .where(JourneyLocation.journey_id == event.journey_id)
        .order_by(JourneyLocation.captured_at.desc())
        .limit(1)
    ) if event.journey_id else None
    event.status = "escalated"
    event.resolved_at = datetime.now(UTC)
    event_type = event.event_type.replace("_", " ")
    latitude = event.latitude if event.latitude is not None else (latest.latitude if latest else None)
    longitude = event.longitude if event.longitude is not None else (latest.longitude if latest else None)
    location_captured_at = (
        event.location_captured_at
        if event.location_captured_at
        else latest.captured_at if latest else event.occurred_at
    )
    alert = await create_safety_alert(
        db,
        user,
        event.event_type,
        f"The traveler confirmed a {event_type} safety concern.",
        f"confirmed-event:{event.id}",
        journey,
        event,
        latitude,
        longitude,
        location_captured_at,
    )
    buddy_alerts = (
        await create_safety_buddy_alerts(
            db,
            journey,
            event.event_type,
            f"The traveler confirmed a {event_type} safety concern.",
            f"confirmed-event:{event.id}",
            safety_alert_id=alert.id,
            latitude=latitude,
            longitude=longitude,
            location_captured_at=location_captured_at,
        )
        if journey
        else []
    )
    await db.commit()
    if journey:
        await broadcast_safety_buddy_alerts(journey.id, buddy_alerts)
    await db.refresh(alert)
    return await serialize_alert(db, alert)


@router.post("/alerts/sos", response_model=SafetyAlertRead, status_code=status.HTTP_201_CREATED)
async def create_sos_alert(
    payload: SOSAlertCreate,
    response: Response,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SafetyAlertRead:
    if payload.share_location and payload.location_captured_at:
        captured_at = payload.location_captured_at.astimezone(UTC)
        now = datetime.now(UTC)
        if captured_at > now + timedelta(minutes=1) or captured_at < now - timedelta(minutes=5):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Refresh your location before sending an SOS alert",
            )

    journey = None
    if payload.journey_id:
        journey = await db.scalar(
            select(Journey).where(
                Journey.id == payload.journey_id,
                Journey.user_id == user.id,
            )
        )
        if journey is None or journey.status not in ("active", "paused"):
            raise HTTPException(status_code=404, detail="Active journey not found")
    else:
        journey = await db.scalar(
            select(Journey)
            .where(
                Journey.user_id == user.id,
                Journey.status == "active",
            )
            .order_by(Journey.started_at.desc())
            .limit(1)
        )

    trigger_key = (
        f"sos:{user.id}:{payload.request_id}"
        if payload.request_id
        else None
    )
    if trigger_key:
        existing = await db.scalar(
            select(SafetyAlert).where(
                SafetyAlert.user_id == user.id,
                SafetyAlert.trigger_key == trigger_key,
            )
        )
        if existing is not None:
            response.status_code = status.HTTP_200_OK
            return await serialize_alert(db, existing)

    occurred_at = datetime.now(UTC)
    event = SafetyEvent(
        user_id=user.id,
        journey_id=journey.id if journey else None,
        event_type="sos",
        status="escalated",
        details={"location_shared": payload.share_location},
        latitude=payload.latitude if payload.share_location else None,
        longitude=payload.longitude if payload.share_location else None,
        location_captured_at=payload.location_captured_at.astimezone(UTC)
        if payload.share_location and payload.location_captured_at
        else None,
        dedupe_key=trigger_key or f"sos:{uuid4()}",
        occurred_at=occurred_at,
        resolved_at=occurred_at,
    )
    try:
        db.add(event)
        await db.flush()
        alert = await create_safety_alert(
            db,
            user,
            "sos",
            "The traveler requested emergency assistance.",
            trigger_key or f"sos:{event.id}",
            journey,
            event,
            payload.latitude if payload.share_location else None,
            payload.longitude if payload.share_location else None,
            payload.location_captured_at.astimezone(UTC)
            if payload.share_location and payload.location_captured_at
            else None,
        )
        if journey:
            db.add(JourneyEvent(journey_id=journey.id, event_type="sos_alert_created"))
        buddy_alerts = (
            await create_safety_buddy_alerts(
                db,
                journey,
                "sos",
                "The traveler requested emergency assistance.",
                f"sos:{event.id}",
                safety_alert_id=alert.id,
                latitude=alert.latitude,
                longitude=alert.longitude,
                location_captured_at=alert.location_captured_at,
            )
            if journey
            else []
        )
        await db.commit()
    except IntegrityError:
        await db.rollback()
        if not trigger_key:
            raise
        existing = await db.scalar(
            select(SafetyAlert).where(
                SafetyAlert.user_id == user.id,
                SafetyAlert.trigger_key == trigger_key,
            )
        )
        if existing is None:
            raise
        response.status_code = status.HTTP_200_OK
        return await serialize_alert(db, existing)

    if journey:
        await broadcast_safety_buddy_alerts(journey.id, buddy_alerts)
    await db.refresh(alert)
    return await serialize_alert(db, alert)


@router.get("/alerts", response_model=list[SafetyAlertRead])
async def list_safety_alerts(
    limit: int = 50,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[SafetyAlertRead]:
    result = await db.execute(
        select(SafetyAlert)
        .where(SafetyAlert.user_id == user.id)
        .order_by(SafetyAlert.created_at.desc())
        .limit(min(max(limit, 1), 100))
    )
    return [
        await serialize_alert(db, alert)
        for alert in result.scalars().all()
    ]


@router.get("/alerts/{alert_id}", response_model=SafetyAlertRead)
async def read_safety_alert(
    alert_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SafetyAlertRead:
    alert = await get_owned_alert(alert_id, user.id, db)
    return await serialize_alert(db, alert)


@router.post("/alerts/{alert_id}/cancel", response_model=SafetyAlertRead)
async def cancel_safety_alert(
    alert_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SafetyAlertRead:
    alert = await db.scalar(
        select(SafetyAlert)
        .where(SafetyAlert.id == alert_id, SafetyAlert.user_id == user.id)
        .with_for_update()
    )
    if alert is None:
        raise HTTPException(status_code=404, detail="Safety alert not found")
    if alert.status == "cancelled":
        raise HTTPException(status_code=409, detail="This alert is already cancelled")

    initial_result = await db.execute(
        select(SafetyAlertDelivery).where(
            SafetyAlertDelivery.alert_id == alert.id,
            SafetyAlertDelivery.message_type == "initial",
        )
    )
    initial_deliveries = list(initial_result.scalars().all())
    alert.status = "cancelled"
    alert.cancelled_at = datetime.now(UTC)
    alert.description = f"False alarm: {alert.description}"
    for delivery in initial_deliveries:
        if delivery.status == "pending":
            delivery.status = "cancelled"
        elif delivery.status in ("sending", "queued", "sent", "delivered"):
            db.add(
                SafetyAlertDelivery(
                    alert_id=alert.id,
                    contact_id=delivery.contact_id,
                    contact_name=delivery.contact_name,
                    phone=delivery.phone,
                    message_type="cancellation",
                    status="pending",
                )
            )
    if alert.safety_event_id:
        event = await db.get(SafetyEvent, alert.safety_event_id)
        if event:
            event.status = "cancelled"
            event.resolved_at = alert.cancelled_at
    await db.commit()
    await db.refresh(alert)
    return await serialize_alert(db, alert)


@router.post("/alerts/{alert_id}/retry", response_model=SafetyAlertRead)
async def retry_safety_alert(
    alert_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SafetyAlertRead:
    alert = await db.scalar(
        select(SafetyAlert)
        .where(SafetyAlert.id == alert_id, SafetyAlert.user_id == user.id)
        .with_for_update()
    )
    if alert is None:
        raise HTTPException(status_code=404, detail="Safety alert not found")
    if alert.status == "cancelled":
        raise HTTPException(status_code=409, detail="A cancelled alert cannot be retried")
    if not sms_provider_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="SMS delivery is not configured on the server",
        )

    result = await db.execute(
        select(SafetyAlertDelivery).where(
            SafetyAlertDelivery.alert_id == alert.id,
            SafetyAlertDelivery.message_type == "initial",
            SafetyAlertDelivery.status.in_(("failed", "unknown", "unconfigured")),
        )
    )
    deliveries = list(result.scalars().all())
    if not deliveries:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This alert has no failed or uncertain messages to retry",
        )
    for delivery in deliveries:
        delivery.status = "pending"
        delivery.last_error = None
    alert.status = "pending"
    await db.commit()
    await db.refresh(alert)
    return await serialize_alert(db, alert)


@router.post("/webhooks/twilio/sms-status", status_code=status.HTTP_204_NO_CONTENT)
async def twilio_sms_status(request: Request, db: AsyncSession = Depends(get_db)) -> Response:
    settings = get_settings()
    auth_token = settings.twilio_auth_token
    signature = request.headers.get("X-Twilio-Signature")
    if not settings.public_api_base_url or auth_token is None or not signature:
        raise HTTPException(status_code=403, detail="SMS status callback is not authorized")

    body = (await request.body()).decode("utf-8")
    form_items = parse_qsl(body, keep_blank_values=True)
    callback_url = f"{settings.public_api_base_url}{request.url.path}"
    if request.url.query:
        callback_url += f"?{request.url.query}"
    signed_value = callback_url + "".join(
        key + "".join(value for item_key, value in form_items if item_key == key)
        for key in sorted({key for key, _ in form_items})
    )
    expected_signature = base64.b64encode(
        hmac.new(
            auth_token.get_secret_value().encode("utf-8"),
            signed_value.encode("utf-8"),
            hashlib.sha1,
        ).digest()
    ).decode("ascii")
    if not hmac.compare_digest(signature, expected_signature):
        raise HTTPException(status_code=403, detail="Invalid SMS status callback signature")

    try:
        query = dict(parse_qsl(request.url.query))
        delivery_id = UUID(query["delivery_id"])
    except (KeyError, ValueError):
        raise HTTPException(status_code=400, detail="Missing or invalid delivery id") from None

    delivery = await db.get(SafetyAlertDelivery, delivery_id)
    if delivery is None or delivery.provider_message_id != dict(form_items).get("MessageSid"):
        raise HTTPException(status_code=404, detail="SMS delivery was not found")

    provider_status = dict(form_items).get("MessageStatus", "")
    status_map = {
        "accepted": "queued",
        "scheduled": "queued",
        "queued": "queued",
        "sending": "queued",
        "sent": "sent",
        "delivered": "delivered",
        "failed": "failed",
        "undelivered": "failed",
        "canceled": "cancelled",
    }
    mapped_status = status_map.get(provider_status)
    if mapped_status is None:
        raise HTTPException(status_code=400, detail="Unsupported SMS delivery status")
    terminal_statuses = {"delivered", "failed", "cancelled"}
    if delivery.status not in terminal_statuses:
        delivery.status = mapped_status
        delivery.last_error = (
            dict(form_items).get("ErrorMessage") or dict(form_items).get("ErrorCode")
            if mapped_status == "failed"
            else None
        )
    await refresh_alert_status(db, delivery.alert_id)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
