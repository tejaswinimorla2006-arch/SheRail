from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user
from app.models import PushDeviceToken, User, UserNotification
from app.schemas import ExpoPushTokenCreate, PushDeviceStatusRead, UserNotificationRead

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("/devices", response_model=PushDeviceStatusRead)
async def push_device_status(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PushDeviceStatusRead:
    active_device = await db.scalar(
        select(PushDeviceToken.id)
        .where(
            PushDeviceToken.user_id == user.id,
            PushDeviceToken.is_active.is_(True),
        )
        .limit(1)
    )
    return PushDeviceStatusRead(enabled=active_device is not None)


@router.post("/devices", status_code=status.HTTP_204_NO_CONTENT)
async def register_push_device(
    payload: ExpoPushTokenCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    device = await db.scalar(
        select(PushDeviceToken)
        .where(PushDeviceToken.expo_push_token == payload.expo_push_token)
        .with_for_update()
    )
    if device is None:
        device = PushDeviceToken(
            user_id=user.id,
            expo_push_token=payload.expo_push_token,
            platform=payload.platform,
            is_active=True,
        )
        db.add(device)
    else:
        device.user_id = user.id
        device.platform = payload.platform
        device.is_active = True
        device.last_seen_at = datetime.now(UTC)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        device = await db.scalar(
            select(PushDeviceToken).where(
                PushDeviceToken.expo_push_token == payload.expo_push_token
            )
        )
        if device is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Could not register this notification device",
            ) from None
        device.user_id = user.id
        device.platform = payload.platform
        device.is_active = True
        device.last_seen_at = datetime.now(UTC)
        await db.commit()


@router.delete("/devices", status_code=status.HTTP_204_NO_CONTENT)
async def unregister_push_device(
    payload: ExpoPushTokenCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    device = await db.scalar(
        select(PushDeviceToken).where(
            PushDeviceToken.user_id == user.id,
            PushDeviceToken.expo_push_token == payload.expo_push_token,
        )
    )
    if device is not None:
        device.is_active = False
        await db.commit()


@router.post("/devices/revoke-all", status_code=status.HTTP_204_NO_CONTENT)
async def unregister_all_push_devices(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    await db.execute(
        update(PushDeviceToken)
        .where(
            PushDeviceToken.user_id == user.id,
            PushDeviceToken.is_active.is_(True),
        )
        .values(is_active=False)
    )
    await db.commit()


@router.get("", response_model=list[UserNotificationRead])
async def list_notifications(
    unread_only: bool = False,
    limit: int = Query(default=50, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[UserNotificationRead]:
    statement = select(UserNotification).where(UserNotification.user_id == user.id)
    if unread_only:
        statement = statement.where(UserNotification.read_at.is_(None))
    result = await db.execute(
        statement.order_by(UserNotification.created_at.desc()).limit(limit)
    )
    return list(result.scalars().all())


@router.get("/unread-count")
async def unread_notification_count(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, int]:
    count = await db.scalar(
        select(func.count(UserNotification.id)).where(
            UserNotification.user_id == user.id,
            UserNotification.read_at.is_(None),
        )
    )
    return {"count": count or 0}


@router.post("/read-all", status_code=status.HTTP_204_NO_CONTENT)
async def mark_all_notifications_read(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    await db.execute(
        update(UserNotification)
        .where(
            UserNotification.user_id == user.id,
            UserNotification.read_at.is_(None),
        )
        .values(read_at=datetime.now(UTC))
    )
    await db.commit()


@router.post("/{notification_id}/read", response_model=UserNotificationRead)
async def mark_notification_read(
    notification_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> UserNotificationRead:
    from uuid import UUID

    try:
        parsed_id = UUID(notification_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Notification not found",
        ) from None
    notification = await db.scalar(
        select(UserNotification)
        .where(
            UserNotification.id == parsed_id,
            UserNotification.user_id == user.id,
        )
        .with_for_update()
    )
    if notification is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Notification not found",
        )
    notification.read_at = notification.read_at or datetime.now(UTC)
    await db.commit()
    return notification
