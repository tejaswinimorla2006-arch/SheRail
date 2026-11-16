from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user
from app.models import Journey, JourneyEvent, JourneyLocation, JourneyShare, SafetyEvent, User
from app.schemas import (
    JourneyCreate,
    JourneyDetail,
    JourneyEventRead,
    JourneyLocationRead,
    JourneyShareCreate,
    JourneyShareRead,
    JourneySharedSummary,
    ExpectedRouteUpdate,
    JourneySafetySettingsUpdate,
    JourneyStatus,
    JourneySummary,
    LocationConsentRequest,
)
from app.safety_buddy_alerts import (
    broadcast_safety_buddy_alerts,
    create_safety_buddy_alerts,
)

router = APIRouter(prefix="/journeys", tags=["journeys"])


async def get_owned_journey(
    journey_id: UUID,
    user_id: UUID,
    db: AsyncSession,
) -> Journey:
    result = await db.execute(
        select(Journey).where(Journey.id == journey_id, Journey.user_id == user_id)
    )
    journey = result.scalar_one_or_none()
    if journey is None:
        raise HTTPException(status_code=404, detail="Journey not found")
    return journey


async def get_journey_detail(db: AsyncSession, journey: Journey) -> JourneyDetail:
    locations_result = await db.execute(
        select(JourneyLocation)
        .where(JourneyLocation.journey_id == journey.id)
        .order_by(JourneyLocation.captured_at, JourneyLocation.id)
    )
    events_result = await db.execute(
        select(JourneyEvent)
        .where(JourneyEvent.journey_id == journey.id)
        .order_by(JourneyEvent.occurred_at, JourneyEvent.id)
    )
    shares_result = await db.execute(
        select(JourneyShare, User)
        .join(User, JourneyShare.recipient_user_id == User.id)
        .where(JourneyShare.journey_id == journey.id)
        .order_by(JourneyShare.created_at)
    )

    return JourneyDetail(
        **JourneySummary.model_validate(journey).model_dump(),
        locations=[JourneyLocationRead.model_validate(item) for item in locations_result.scalars()],
        events=[JourneyEventRead.model_validate(item) for item in events_result.scalars()],
        shares=[
            JourneyShareRead(
                id=share.id,
                recipient_user_id=recipient.id,
                recipient_name=recipient.name,
                recipient_email=recipient.email,
                created_at=share.created_at,
            )
            for share, recipient in shares_result.all()
        ],
    )


def add_event(db: AsyncSession, journey_id: UUID, event_type: str) -> None:
    db.add(JourneyEvent(journey_id=journey_id, event_type=event_type))


async def broadcast_tracking_state(
    db: AsyncSession,
    journey_id: UUID,
    user_id: UUID,
    event_type: str,
) -> None:
    recipient_result = await db.execute(
        select(JourneyShare.recipient_user_id).where(
            JourneyShare.journey_id == journey_id
        )
    )
    from app.live import connection_manager

    await connection_manager.broadcast(
        journey_id,
        {"type": event_type, "journey_id": str(journey_id)},
        journey_owner_id=user_id,
        recipient_ids=set(recipient_result.scalars().all()),
    )


@router.post("", response_model=JourneyDetail, status_code=status.HTTP_201_CREATED)
async def create_journey(
    payload: JourneyCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JourneyDetail:
    open_journey_result = await db.execute(
        select(Journey.id)
        .where(
            Journey.user_id == user.id,
            Journey.status != JourneyStatus.COMPLETED.value,
        )
        .limit(1)
    )
    if open_journey_result.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="End your current journey before creating another",
        )

    journey = Journey(
        user_id=user.id,
        transport_mode=payload.transport_mode.value,
        origin=payload.origin or None,
        destination=payload.destination or None,
        transport_details=payload.transport_details,
    )
    db.add(journey)
    await db.flush()
    add_event(db, journey.id, "created")
    await db.commit()
    await db.refresh(journey)
    return await get_journey_detail(db, journey)


@router.get("", response_model=list[JourneySummary])
async def list_journeys(
    journey_status: JourneyStatus | None = Query(default=None, alias="status"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[Journey]:
    statement = select(Journey).where(Journey.user_id == user.id)
    if journey_status is not None:
        statement = statement.where(Journey.status == journey_status.value)
    result = await db.execute(statement.order_by(Journey.created_at.desc()))
    return list(result.scalars().all())


@router.get("/shared-with-me", response_model=list[JourneySharedSummary])
async def list_shared_journeys(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[JourneySharedSummary]:
    result = await db.execute(
        select(Journey, User)
        .join(JourneyShare, JourneyShare.journey_id == Journey.id)
        .join(User, Journey.user_id == User.id)
        .where(
            JourneyShare.recipient_user_id == user.id,
            Journey.sharing_enabled.is_(True),
            Journey.location_recording_enabled.is_(True),
            Journey.status == JourneyStatus.ACTIVE.value,
        )
        .order_by(Journey.started_at.desc())
    )
    summaries = []
    for journey, owner in result.all():
        journey_data = JourneySummary.model_validate(journey).model_dump()
        journey_data["expected_route"] = []
        summaries.append(JourneySharedSummary(**journey_data, owner_name=owner.name))
    return summaries


@router.get("/shared-with-me/{journey_id}", response_model=JourneySharedSummary)
async def get_shared_journey(
    journey_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JourneySharedSummary:
    result = await db.execute(
        select(Journey, User)
        .join(JourneyShare, JourneyShare.journey_id == Journey.id)
        .join(User, Journey.user_id == User.id)
        .where(
            Journey.id == journey_id,
            JourneyShare.recipient_user_id == user.id,
            Journey.sharing_enabled.is_(True),
            Journey.location_recording_enabled.is_(True),
            Journey.status == JourneyStatus.ACTIVE.value,
        )
    )
    record = result.one_or_none()
    if record is None:
        raise HTTPException(status_code=404, detail="Shared journey not found")

    journey, owner = record
    latest_result = await db.execute(
        select(JourneyLocation)
        .where(JourneyLocation.journey_id == journey.id)
        .order_by(JourneyLocation.captured_at.desc())
        .limit(1)
    )
    latest = latest_result.scalar_one_or_none()
    return JourneySharedSummary(
        **{
            **JourneySummary.model_validate(journey).model_dump(),
            "expected_route": [],
        },
        owner_name=owner.name,
        latest_location=JourneyLocationRead.model_validate(latest) if latest else None,
    )


@router.get("/{journey_id}", response_model=JourneyDetail)
async def read_journey(
    journey_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JourneyDetail:
    journey = await get_owned_journey(journey_id, user.id, db)
    return await get_journey_detail(db, journey)


@router.patch("/{journey_id}/safety", response_model=JourneyDetail)
async def update_journey_safety(
    journey_id: UUID,
    payload: JourneySafetySettingsUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JourneyDetail:
    journey = await get_owned_journey(journey_id, user.id, db)
    if journey.status != JourneyStatus.ACTIVE.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Safety monitoring can only be configured during an active journey",
        )
    if not payload.consent and (
        payload.checkin_interval_minutes is not None
        or payload.route_deviation_enabled
        or payload.long_stop_enabled
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Enable safety monitoring consent before configuring its features",
        )
    if payload.route_deviation_enabled and len(journey.expected_route) < 2:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Add at least two expected-route waypoints before enabling deviation alerts",
        )
    if (
        (payload.route_deviation_enabled or payload.long_stop_enabled)
        and not journey.location_recording_enabled
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Enable GPS recording before configuring GPS safety monitors",
        )

    now = datetime.now(UTC)
    journey.safety_monitoring_consent = payload.consent
    journey.checkin_interval_minutes = payload.checkin_interval_minutes
    journey.checkin_grace_minutes = payload.checkin_grace_minutes
    journey.checkin_due_at = (
        now + timedelta(minutes=payload.checkin_interval_minutes)
        if payload.consent and payload.checkin_interval_minutes
        else None
    )
    journey.checkin_consent_at = now if payload.consent else None
    journey.route_deviation_enabled = payload.route_deviation_enabled
    journey.route_deviation_threshold_m = payload.route_deviation_threshold_m
    journey.long_stop_enabled = payload.long_stop_enabled
    journey.long_stop_minutes = payload.long_stop_minutes
    journey.stop_radius_m = payload.stop_radius_m
    if not payload.consent or not payload.route_deviation_enabled:
        journey.deviation_active = False
        journey.deviation_started_at = None
    if not payload.consent or not payload.long_stop_enabled:
        journey.stationary_since = None
        journey.long_stop_alerted_at = None
    add_event(
        db,
        journey.id,
        "safety_monitoring_enabled" if payload.consent else "safety_monitoring_disabled",
    )
    await db.commit()
    await db.refresh(journey)
    return await get_journey_detail(db, journey)


@router.put("/{journey_id}/expected-route", response_model=JourneyDetail)
async def update_expected_route(
    journey_id: UUID,
    payload: ExpectedRouteUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JourneyDetail:
    journey = await get_owned_journey(journey_id, user.id, db)
    journey.expected_route = [point.model_dump() for point in payload.points]
    journey.deviation_active = False
    journey.deviation_started_at = None
    add_event(db, journey.id, "expected_route_updated")
    await db.commit()
    await db.refresh(journey)
    return await get_journey_detail(db, journey)


@router.post("/{journey_id}/check-in", response_model=JourneyDetail)
async def check_in(
    journey_id: UUID,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key", max_length=128),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JourneyDetail:
    journey = await db.scalar(
        select(Journey)
        .where(Journey.id == journey_id, Journey.user_id == user.id)
        .with_for_update()
    )
    if journey is None:
        raise HTTPException(status_code=404, detail="Journey not found")
    dedupe_key = (
        f"checkin:{journey.id}:{idempotency_key}"
        if idempotency_key
        else None
    )
    if dedupe_key:
        existing = await db.scalar(
            select(SafetyEvent.id).where(
                SafetyEvent.user_id == user.id,
                SafetyEvent.journey_id == journey.id,
                SafetyEvent.event_type == "checkin_completed",
                SafetyEvent.dedupe_key == dedupe_key,
            )
        )
        if existing is not None:
            return await get_journey_detail(db, journey)

    if (
        journey.status != JourneyStatus.ACTIVE.value
        or not journey.safety_monitoring_consent
        or not journey.checkin_interval_minutes
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Safety check-ins are not enabled for this active journey",
        )

    now = datetime.now(UTC)
    journey.checkin_due_at = now + timedelta(minutes=journey.checkin_interval_minutes)
    db.add(
        SafetyEvent(
            user_id=user.id,
            journey_id=journey.id,
            event_type="checkin_completed",
            status="completed",
            details={"next_checkin_due_at": journey.checkin_due_at.isoformat()},
            dedupe_key=dedupe_key or f"checkin:{journey.id}:{now.isoformat()}",
            occurred_at=now,
        )
    )
    add_event(db, journey.id, "checkin_completed")
    await db.commit()
    await db.refresh(journey)
    return await get_journey_detail(db, journey)


async def transition(
    journey_id: UUID,
    user: User,
    db: AsyncSession,
    expected_status: JourneyStatus,
    next_status: JourneyStatus,
    event_type: str,
    consent: bool | None = None,
) -> JourneyDetail:
    journey = await get_owned_journey(journey_id, user.id, db)
    if journey.status != expected_status.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Journey must be {expected_status.value} to {event_type}",
        )
    if consent is False:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Location consent is required to start or resume tracking",
        )
    if next_status is JourneyStatus.ACTIVE:
        active_result = await db.execute(
            select(Journey.id)
            .where(
                Journey.user_id == user.id,
                Journey.status == JourneyStatus.ACTIVE.value,
                Journey.id != journey.id,
            )
            .limit(1)
        )
        if active_result.scalar_one_or_none() is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="End or pause your other active journey before starting this one",
            )

    now = datetime.now(UTC)
    journey.status = next_status.value
    buddy_alerts = []
    if journey.sharing_enabled and event_type in ("paused", "resumed", "ended"):
        buddy_alerts = await create_safety_buddy_alerts(
            db,
            journey,
            "journey_status",
            f"The shared journey was {event_type}.",
            f"journey:{journey.id}:{event_type}:{now.isoformat()}",
        )
    if next_status is JourneyStatus.ACTIVE:
        journey.location_recording_enabled = True
        journey.location_consent_at = now
        if expected_status is JourneyStatus.PLANNED:
            journey.started_at = now
        if journey.safety_monitoring_consent and journey.checkin_interval_minutes:
            journey.checkin_due_at = now + timedelta(minutes=journey.checkin_interval_minutes)
        add_event(db, journey.id, "location_consent_granted")
    elif next_status is JourneyStatus.PAUSED:
        journey.paused_at = now
        journey.location_recording_enabled = False
        journey.checkin_due_at = None
        add_event(db, journey.id, "location_recording_paused")
    elif next_status is JourneyStatus.COMPLETED:
        journey.ended_at = now
        journey.location_recording_enabled = False
        journey.sharing_enabled = False
        journey.checkin_due_at = None
        journey.safety_monitoring_consent = False
        await db.execute(delete(JourneyShare).where(JourneyShare.journey_id == journey.id))

    add_event(db, journey.id, event_type)
    await db.commit()
    await db.refresh(journey)
    await broadcast_safety_buddy_alerts(journey.id, buddy_alerts)
    return await get_journey_detail(db, journey)


@router.post("/{journey_id}/start", response_model=JourneyDetail)
async def start_journey(
    journey_id: UUID,
    payload: LocationConsentRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JourneyDetail:
    detail = await transition(
        journey_id,
        user,
        db,
        JourneyStatus.PLANNED,
        JourneyStatus.ACTIVE,
        "started",
        consent=payload.consent,
    )
    await broadcast_tracking_state(db, detail.id, user.id, "tracking_resumed")
    return detail


@router.post("/{journey_id}/pause", response_model=JourneyDetail)
async def pause_journey(
    journey_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JourneyDetail:
    detail = await transition(
        journey_id,
        user,
        db,
        JourneyStatus.ACTIVE,
        JourneyStatus.PAUSED,
        "paused",
    )
    await broadcast_tracking_state(db, detail.id, user.id, "tracking_paused")
    return detail


@router.post("/{journey_id}/resume", response_model=JourneyDetail)
async def resume_journey(
    journey_id: UUID,
    payload: LocationConsentRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JourneyDetail:
    detail = await transition(
        journey_id,
        user,
        db,
        JourneyStatus.PAUSED,
        JourneyStatus.ACTIVE,
        "resumed",
        consent=payload.consent,
    )
    await broadcast_tracking_state(db, detail.id, user.id, "tracking_resumed")
    return detail


@router.post("/{journey_id}/end", response_model=JourneyDetail)
async def end_journey(
    journey_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JourneyDetail:
    journey = await get_owned_journey(journey_id, user.id, db)
    if journey.status not in (
        JourneyStatus.PLANNED.value,
        JourneyStatus.ACTIVE.value,
        JourneyStatus.PAUSED.value,
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only a planned, active, or paused journey can be ended",
        )
    previous_shares = await db.execute(
        select(JourneyShare.recipient_user_id).where(
            JourneyShare.journey_id == journey.id
        )
    )
    recipient_ids = set(previous_shares.scalars().all())
    detail = await transition(
        journey_id,
        user,
        db,
        JourneyStatus(journey.status),
        JourneyStatus.COMPLETED,
        "cancelled" if journey.status == JourneyStatus.PLANNED.value else "ended",
    )
    from app.live import connection_manager

    await connection_manager.close_connections(
        journey.id,
        {user.id} | recipient_ids,
        {"type": "journey_ended", "journey_id": str(journey.id)},
    )
    return detail


@router.patch("/{journey_id}/tracking", response_model=JourneyDetail)
async def set_location_tracking(
    journey_id: UUID,
    payload: LocationConsentRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JourneyDetail:
    journey = await get_owned_journey(journey_id, user.id, db)
    if journey.status != JourneyStatus.ACTIVE.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Location tracking can only be changed during an active journey",
        )

    journey.location_recording_enabled = payload.consent
    journey.location_consent_at = datetime.now(UTC) if payload.consent else None
    revoked_recipient_ids: set[UUID] = set()
    if not payload.consent:
        recipient_result = await db.execute(
            select(JourneyShare.recipient_user_id).where(
                JourneyShare.journey_id == journey.id
            )
        )
        revoked_recipient_ids = set(recipient_result.scalars().all())
        await db.execute(
            delete(JourneyShare).where(JourneyShare.journey_id == journey.id)
        )
        journey.sharing_enabled = False
    add_event(
        db,
        journey.id,
        "location_consent_granted"
        if payload.consent
        else "location_consent_revoked_and_shares_removed",
    )
    await db.commit()
    await db.refresh(journey)
    if revoked_recipient_ids:
        from app.live import connection_manager

        await connection_manager.close_connections(
            journey.id,
            revoked_recipient_ids,
            {"type": "sharing_stopped", "journey_id": str(journey.id)},
        )
    else:
        await broadcast_tracking_state(
            db,
            journey.id,
            user.id,
            "tracking_resumed" if payload.consent else "tracking_paused",
        )
    return await get_journey_detail(db, journey)


@router.get("/{journey_id}/shares", response_model=list[JourneyShareRead])
async def list_journey_shares(
    journey_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[JourneyShareRead]:
    journey = await get_owned_journey(journey_id, user.id, db)
    result = await db.execute(
        select(JourneyShare, User)
        .join(User, JourneyShare.recipient_user_id == User.id)
        .where(JourneyShare.journey_id == journey.id)
        .order_by(JourneyShare.created_at)
    )
    return [
        JourneyShareRead(
            id=share.id,
            recipient_user_id=recipient.id,
            recipient_name=recipient.name,
            recipient_email=recipient.email,
            created_at=share.created_at,
        )
        for share, recipient in result.all()
    ]


@router.post(
    "/{journey_id}/shares",
    response_model=JourneyShareRead,
    status_code=status.HTTP_201_CREATED,
)
async def share_journey(
    journey_id: UUID,
    payload: JourneyShareCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JourneyShareRead:
    journey = await get_owned_journey(journey_id, user.id, db)
    if (
        journey.status != JourneyStatus.ACTIVE.value
        or not journey.location_recording_enabled
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Start location tracking before sharing this journey",
        )

    recipient_result = await db.execute(
        select(User).where(User.email == str(payload.recipient_email))
    )
    recipient = recipient_result.scalar_one_or_none()
    if recipient is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="That email does not belong to a SheRail account",
        )
    if recipient.id == user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You cannot share a journey with your own account",
        )

    existing_result = await db.execute(
        select(JourneyShare).where(
            JourneyShare.journey_id == journey.id,
            JourneyShare.recipient_user_id == recipient.id,
        )
    )
    share = existing_result.scalar_one_or_none()
    if share is None:
        share = JourneyShare(
            journey_id=journey.id,
            recipient_user_id=recipient.id,
        )
        db.add(share)
    journey.sharing_enabled = True
    add_event(db, journey.id, "location_shared")
    await db.commit()
    await db.refresh(share)
    return JourneyShareRead(
        id=share.id,
        recipient_user_id=recipient.id,
        recipient_name=recipient.name,
        recipient_email=recipient.email,
        created_at=share.created_at,
    )


@router.delete("/{journey_id}/shares/{recipient_user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_journey_share(
    journey_id: UUID,
    recipient_user_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    journey = await get_owned_journey(journey_id, user.id, db)
    share_result = await db.execute(
        select(JourneyShare).where(
            JourneyShare.journey_id == journey.id,
            JourneyShare.recipient_user_id == recipient_user_id,
        )
    )
    share = share_result.scalar_one_or_none()
    if share is None:
        raise HTTPException(status_code=404, detail="Journey share not found")
    await db.delete(share)
    remaining = await db.scalar(
        select(JourneyShare.id)
        .where(JourneyShare.journey_id == journey.id)
        .limit(1)
    )
    journey.sharing_enabled = remaining is not None
    add_event(db, journey.id, "location_share_revoked")
    await db.commit()
    from app.live import connection_manager

    await connection_manager.close_connections(
        journey.id,
        {recipient_user_id},
        {"type": "sharing_stopped", "journey_id": str(journey.id)},
    )


@router.delete("/{journey_id}/shares", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_all_journey_shares(
    journey_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    journey = await get_owned_journey(journey_id, user.id, db)
    previous_shares = await db.execute(
        select(JourneyShare.recipient_user_id).where(
            JourneyShare.journey_id == journey.id
        )
    )
    recipient_ids = set(previous_shares.scalars().all())
    await db.execute(delete(JourneyShare).where(JourneyShare.journey_id == journey.id))
    journey.sharing_enabled = False
    add_event(db, journey.id, "location_sharing_stopped")
    await db.commit()
    from app.live import connection_manager

    await connection_manager.close_connections(
        journey.id,
        recipient_ids,
        {"type": "sharing_stopped", "journey_id": str(journey.id)},
    )
