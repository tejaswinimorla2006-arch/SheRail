from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Journey, JourneyShare, SafetyBuddyAlert, SafetyBuddyLink
from app.notification_delivery import enqueue_notification


async def create_safety_buddy_alerts(
    db: AsyncSession,
    journey: Journey,
    alert_type: str,
    description: str,
    trigger_id: str,
    *,
    safety_alert_id: UUID | None = None,
    latitude: float | None = None,
    longitude: float | None = None,
    location_captured_at: datetime | None = None,
) -> list[SafetyBuddyAlert]:
    if not journey.sharing_enabled:
        return []

    shares_result = await db.execute(
        select(JourneyShare.recipient_user_id).where(
            JourneyShare.journey_id == journey.id
        )
    )
    shared_user_ids = set(shares_result.scalars().all())
    if not shared_user_ids:
        return []

    links_result = await db.execute(
        select(SafetyBuddyLink).where(
            SafetyBuddyLink.status == "accepted",
            or_(
                and_(
                    SafetyBuddyLink.user_one_id == journey.user_id,
                    SafetyBuddyLink.user_two_id.in_(shared_user_ids),
                ),
                and_(
                    SafetyBuddyLink.user_two_id == journey.user_id,
                    SafetyBuddyLink.user_one_id.in_(shared_user_ids),
                ),
            ),
        )
    )

    alerts = []
    for link in links_result.scalars().all():
        buddy_user_id = (
            link.user_two_id if link.user_one_id == journey.user_id else link.user_one_id
        )
        dedupe_key = f"{trigger_id}:{link.id}"
        exists = await db.scalar(
            select(SafetyBuddyAlert.id).where(
                SafetyBuddyAlert.dedupe_key == dedupe_key
            )
        )
        if exists is not None:
            continue
        alert = SafetyBuddyAlert(
            buddy_link_id=link.id,
            owner_user_id=journey.user_id,
            buddy_user_id=buddy_user_id,
            journey_id=journey.id,
            safety_alert_id=safety_alert_id,
            alert_type=alert_type,
            description=description[:400],
            latitude=latitude,
            longitude=longitude,
            location_captured_at=location_captured_at,
            dedupe_key=dedupe_key,
            created_at=datetime.now(UTC),
        )
        db.add(alert)
        enqueue_notification(
            db,
            buddy_user_id,
            "safety_buddy_alert",
            "Safety Buddy alert",
            description,
            {
                "screen": "Notifications",
                "buddy_alert_id": str(alert.id),
                "journey_id": str(journey.id),
            },
        )
        alerts.append(alert)

    if alerts:
        await db.flush()
    return alerts


async def broadcast_safety_buddy_alerts(
    journey_id: UUID,
    alerts: list[SafetyBuddyAlert],
) -> None:
    if not alerts:
        return
    from app.live import connection_manager

    for alert in alerts:
        await connection_manager.send_to_users(
            journey_id,
            {alert.buddy_user_id},
            {
                "type": "safety_buddy_alert",
                "alert": {
                    "id": str(alert.id),
                    "owner_user_id": str(alert.owner_user_id),
                    "journey_id": str(alert.journey_id),
                    "safety_alert_id": (
                        str(alert.safety_alert_id) if alert.safety_alert_id else None
                    ),
                    "alert_type": alert.alert_type,
                    "description": alert.description,
                    "latitude": alert.latitude,
                    "longitude": alert.longitude,
                    "location_captured_at": (
                        alert.location_captured_at.isoformat()
                        if alert.location_captured_at
                        else None
                    ),
                    "created_at": alert.created_at.isoformat(),
                },
            },
        )
