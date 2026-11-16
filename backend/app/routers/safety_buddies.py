from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user
from app.models import Journey, JourneyEvent, JourneyShare, SafetyBuddyAlert, SafetyBuddyLink, User
from app.schemas import (
    JourneyShareRead,
    SafetyBuddyAlertRead,
    SafetyBuddyInviteCreate,
    SafetyBuddyInviteResponse,
    SafetyBuddyJourneyShareRequest,
    SafetyBuddyLinkRead,
    SafetyBuddyOverview,
)

router = APIRouter(prefix="/safety-buddies", tags=["safety buddies"])


async def serialize_links(
    db: AsyncSession,
    links: list[SafetyBuddyLink],
    user_id: UUID,
    direction: str,
) -> list[SafetyBuddyLinkRead]:
    peer_ids = {
        link.user_two_id if link.user_one_id == user_id else link.user_one_id
        for link in links
    }
    if not peer_ids:
        return []
    people_result = await db.execute(select(User).where(User.id.in_(peer_ids)))
    people = {person.id: person for person in people_result.scalars().all()}
    return [
        SafetyBuddyLinkRead(
            id=link.id,
            peer_user_id=(
                link.user_two_id if link.user_one_id == user_id else link.user_one_id
            ),
            peer_name=people[
                link.user_two_id if link.user_one_id == user_id else link.user_one_id
            ].name,
            peer_email=people[
                link.user_two_id if link.user_one_id == user_id else link.user_one_id
            ].email,
            status=link.status,
            direction=direction,
            created_at=link.created_at,
            responded_at=link.responded_at,
        )
        for link in links
        if (
            link.user_two_id if link.user_one_id == user_id else link.user_one_id
        ) in people
    ]


@router.get("", response_model=SafetyBuddyOverview)
async def list_safety_buddies(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SafetyBuddyOverview:
    sent_result = await db.execute(
        select(SafetyBuddyLink)
        .where(
            SafetyBuddyLink.invited_by_id == user.id,
            SafetyBuddyLink.status.in_(("pending", "declined")),
        )
        .order_by(SafetyBuddyLink.created_at.desc())
    )
    received_result = await db.execute(
        select(SafetyBuddyLink)
        .where(
            SafetyBuddyLink.invited_by_id != user.id,
            SafetyBuddyLink.status == "pending",
            or_(
                SafetyBuddyLink.user_one_id == user.id,
                SafetyBuddyLink.user_two_id == user.id,
            ),
        )
        .order_by(SafetyBuddyLink.created_at.desc())
    )
    accepted_result = await db.execute(
        select(SafetyBuddyLink)
        .where(
            SafetyBuddyLink.status == "accepted",
            or_(
                SafetyBuddyLink.user_one_id == user.id,
                SafetyBuddyLink.user_two_id == user.id,
            ),
        )
        .order_by(SafetyBuddyLink.created_at.desc())
    )
    return SafetyBuddyOverview(
        sent=await serialize_links(db, list(sent_result.scalars().all()), user.id, "sent"),
        received=await serialize_links(
            db, list(received_result.scalars().all()), user.id, "received"
        ),
        accepted=await serialize_links(
            db, list(accepted_result.scalars().all()), user.id, "accepted"
        ),
    )


@router.post(
    "/invitations",
    response_model=SafetyBuddyLinkRead,
    status_code=status.HTTP_201_CREATED,
)
async def invite_safety_buddy(
    payload: SafetyBuddyInviteCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SafetyBuddyLinkRead:
    recipient = await db.scalar(select(User).where(User.email == str(payload.email)))
    if recipient is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="That email does not belong to a SheRail account",
        )
    if recipient.id == user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You cannot invite your own account",
        )

    invites_today = await db.scalar(
        select(func.count(SafetyBuddyLink.id)).where(
            SafetyBuddyLink.invited_by_id == user.id,
            SafetyBuddyLink.created_at >= datetime.now(UTC) - timedelta(days=1),
        )
    )
    if (invites_today or 0) >= 20:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="You have reached today's invitation limit. Try again tomorrow.",
        )

    user_one_id, user_two_id = sorted((user.id, recipient.id))
    link = await db.scalar(
        select(SafetyBuddyLink)
        .where(
            SafetyBuddyLink.user_one_id == user_one_id,
            SafetyBuddyLink.user_two_id == user_two_id,
        )
        .with_for_update()
    )
    now = datetime.now(UTC)
    if link is not None:
        if link.status == "accepted":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="You are already connected as safety buddies",
            )
        if link.status == "pending":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A safety buddy invitation is already waiting for a response",
            )
        link.invited_by_id = user.id
        link.status = "pending"
        link.created_at = now
        link.responded_at = None
    else:
        link = SafetyBuddyLink(
            user_one_id=user_one_id,
            user_two_id=user_two_id,
            invited_by_id=user.id,
            status="pending",
        )
        db.add(link)
    await db.commit()
    await db.refresh(link)
    return SafetyBuddyLinkRead(
        id=link.id,
        peer_user_id=recipient.id,
        peer_name=recipient.name,
        peer_email=recipient.email,
        status=link.status,
        direction="sent",
        created_at=link.created_at,
        responded_at=link.responded_at,
    )


@router.post(
    "/invitations/{link_id}/respond",
    response_model=SafetyBuddyLinkRead,
)
async def respond_to_invitation(
    link_id: UUID,
    payload: SafetyBuddyInviteResponse,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SafetyBuddyLinkRead:
    link = await db.scalar(
        select(SafetyBuddyLink)
        .where(SafetyBuddyLink.id == link_id)
        .with_for_update()
    )
    if link is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invitation not found")
    if user.id not in (link.user_one_id, link.user_two_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invitation access denied")
    if link.invited_by_id == user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the invited account can respond to this invitation",
        )
    if link.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This invitation has already been answered",
        )

    link.status = "accepted" if payload.accept else "declined"
    link.responded_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(link)
    peer_id = link.user_two_id if link.user_one_id == user.id else link.user_one_id
    peer = await db.get(User, peer_id)
    if peer is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Inviting account not found")
    return SafetyBuddyLinkRead(
        id=link.id,
        peer_user_id=peer.id,
        peer_name=peer.name,
        peer_email=peer.email,
        status=link.status,
        direction="accepted" if payload.accept else "received",
        created_at=link.created_at,
        responded_at=link.responded_at,
    )


@router.delete("/{link_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_safety_buddy(
    link_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    link = await db.scalar(
        select(SafetyBuddyLink)
        .where(SafetyBuddyLink.id == link_id)
        .with_for_update()
    )
    if link is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Safety buddy link not found")
    if user.id not in (link.user_one_id, link.user_two_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Safety buddy access denied")

    user_one_id = link.user_one_id
    user_two_id = link.user_two_id
    shares_result = await db.execute(
        select(JourneyShare, Journey)
        .join(Journey, Journey.id == JourneyShare.journey_id)
        .where(
            or_(
                and_(
                    Journey.user_id == user_one_id,
                    JourneyShare.recipient_user_id == user_two_id,
                ),
                and_(
                    Journey.user_id == user_two_id,
                    JourneyShare.recipient_user_id == user_one_id,
                ),
            )
        )
    )
    revoked = list(shares_result.all())
    for share, _journey in revoked:
        await db.delete(share)
    await db.flush()
    affected_journeys = {journey.id: journey for _, journey in revoked}
    for journey in affected_journeys.values():
        remaining = await db.scalar(
            select(JourneyShare.id)
            .where(JourneyShare.journey_id == journey.id)
            .limit(1)
        )
        journey.sharing_enabled = remaining is not None
        db.add(JourneyEvent(journey_id=journey.id, event_type="safety_buddy_unlinked"))
    await db.delete(link)
    await db.commit()

    from app.live import connection_manager

    for share, journey in revoked:
        await connection_manager.close_connections(
            journey.id,
            {share.recipient_user_id},
            {"type": "sharing_stopped", "journey_id": str(journey.id)},
        )


@router.post(
    "/{buddy_user_id}/journeys/{journey_id}",
    response_model=JourneyShareRead,
    status_code=status.HTTP_201_CREATED,
)
async def share_journey_with_buddy(
    buddy_user_id: UUID,
    journey_id: UUID,
    payload: SafetyBuddyJourneyShareRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JourneyShareRead:
    if not payload.location_consent:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Explicit location consent is required to share a journey",
        )
    journey = await db.scalar(
        select(Journey)
        .where(
            Journey.id == journey_id,
            Journey.user_id == user.id,
        )
        .with_for_update()
    )
    if journey is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Journey not found")
    if journey.status != "active" or not journey.location_recording_enabled:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Start GPS recording before sharing a journey with a safety buddy",
        )
    link = await db.scalar(
        select(SafetyBuddyLink).where(
            SafetyBuddyLink.status == "accepted",
            or_(
                and_(
                    SafetyBuddyLink.user_one_id == user.id,
                    SafetyBuddyLink.user_two_id == buddy_user_id,
                ),
                and_(
                    SafetyBuddyLink.user_two_id == user.id,
                    SafetyBuddyLink.user_one_id == buddy_user_id,
                ),
            ),
        )
    )
    if link is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Accept a safety buddy invitation before sharing a journey",
        )
    recipient = await db.get(User, buddy_user_id)
    if recipient is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Safety buddy not found")
    share = await db.scalar(
        select(JourneyShare).where(
            JourneyShare.journey_id == journey.id,
            JourneyShare.recipient_user_id == buddy_user_id,
        )
    )
    if share is None:
        share = JourneyShare(
            journey_id=journey.id,
            recipient_user_id=buddy_user_id,
        )
        db.add(share)
    journey.sharing_enabled = True
    db.add(JourneyEvent(journey_id=journey.id, event_type="location_shared_with_safety_buddy"))
    await db.commit()
    await db.refresh(share)
    return JourneyShareRead(
        id=share.id,
        recipient_user_id=recipient.id,
        recipient_name=recipient.name,
        recipient_email=recipient.email,
        created_at=share.created_at,
    )


@router.delete(
    "/{buddy_user_id}/journeys/{journey_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def revoke_buddy_journey_share(
    buddy_user_id: UUID,
    journey_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    journey = await db.scalar(
        select(Journey).where(
            Journey.id == journey_id,
            Journey.user_id == user.id,
        )
    )
    if journey is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Journey not found")
    share = await db.scalar(
        select(JourneyShare).where(
            JourneyShare.journey_id == journey.id,
            JourneyShare.recipient_user_id == buddy_user_id,
        )
    )
    if share is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Journey is not shared with this account")
    await db.delete(share)
    remaining = await db.scalar(
        select(JourneyShare.id).where(JourneyShare.journey_id == journey.id).limit(1)
    )
    journey.sharing_enabled = remaining is not None
    db.add(JourneyEvent(journey_id=journey.id, event_type="location_share_revoked"))
    await db.commit()
    from app.live import connection_manager

    await connection_manager.close_connections(
        journey.id,
        {buddy_user_id},
        {"type": "sharing_stopped", "journey_id": str(journey.id)},
    )


@router.get("/alerts", response_model=list[SafetyBuddyAlertRead])
async def list_buddy_alerts(
    limit: int = 50,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[SafetyBuddyAlertRead]:
    result = await db.execute(
        select(SafetyBuddyAlert, User)
        .join(User, User.id == SafetyBuddyAlert.owner_user_id)
        .where(SafetyBuddyAlert.buddy_user_id == user.id)
        .order_by(SafetyBuddyAlert.created_at.desc())
        .limit(min(max(limit, 1), 100))
    )
    return [
        SafetyBuddyAlertRead(
            id=alert.id,
            owner_user_id=alert.owner_user_id,
            owner_name=owner.name,
            journey_id=alert.journey_id,
            safety_alert_id=alert.safety_alert_id,
            alert_type=alert.alert_type,
            description=alert.description,
            latitude=alert.latitude,
            longitude=alert.longitude,
            location_captured_at=alert.location_captured_at,
            created_at=alert.created_at,
            read_at=alert.read_at,
        )
        for alert, owner in result.all()
    ]


@router.post("/alerts/{alert_id}/read", response_model=SafetyBuddyAlertRead)
async def mark_buddy_alert_read(
    alert_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SafetyBuddyAlertRead:
    alert = await db.scalar(
        select(SafetyBuddyAlert)
        .where(
            SafetyBuddyAlert.id == alert_id,
            SafetyBuddyAlert.buddy_user_id == user.id,
        )
        .with_for_update()
    )
    if alert is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Buddy alert not found")
    alert.read_at = alert.read_at or datetime.now(UTC)
    owner = await db.get(User, alert.owner_user_id)
    if owner is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Journey owner not found")
    await db.commit()
    return SafetyBuddyAlertRead(
        id=alert.id,
        owner_user_id=alert.owner_user_id,
        owner_name=owner.name,
        journey_id=alert.journey_id,
        safety_alert_id=alert.safety_alert_id,
        alert_type=alert.alert_type,
        description=alert.description,
        latitude=alert.latitude,
        longitude=alert.longitude,
        location_captured_at=alert.location_captured_at,
        created_at=alert.created_at,
        read_at=alert.read_at,
    )
