from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.dependencies import get_current_admin
from app.models import (
    CommunitySafetyReport,
    CommunitySafetyReportImage,
    RailwayAssistanceRecord,
    SafetyAlert,
    User,
    VerifiedAssistancePoint,
)
from app.notification_delivery import enqueue_notification
from app.schemas import (
    AdminCommunityReportRead,
    AdminOverviewRead,
    AdminSOSAlertRead,
    AdminSOSAlertUpdate,
    AdminSOSDeliveryRead,
    AdminUserRead,
    AdminUserUpdate,
    AssistancePointCreate,
    AssistancePointRead,
    AssistancePointUpdate,
    CommunitySafetyReportReview,
    RailwayAssistanceCreate,
    RailwayAssistanceRead,
    RailwayAssistanceUpdate,
)

router = APIRouter(prefix="/admin", tags=["administration"])


@router.get("/overview", response_model=AdminOverviewRead)
async def admin_overview(
    _: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> AdminOverviewRead:
    users = await db.scalar(select(func.count(User.id)))
    active_users = await db.scalar(
        select(func.count(User.id)).where(User.is_active.is_(True))
    )
    open_sos_alerts = await db.scalar(
        select(func.count(SafetyAlert.id)).where(
            SafetyAlert.admin_status.in_(("open", "investigating"))
        )
    )
    pending_reports = await db.scalar(
        select(func.count(CommunitySafetyReport.id)).where(
            CommunitySafetyReport.status.in_(("pending", "under_review"))
        )
    )
    assistance_points = await db.scalar(
        select(func.count(VerifiedAssistancePoint.id)).where(
            VerifiedAssistancePoint.is_active.is_(True)
        )
    )
    railway_records = await db.scalar(
        select(func.count(RailwayAssistanceRecord.id)).where(
            RailwayAssistanceRecord.is_active.is_(True)
        )
    )
    return AdminOverviewRead(
        users=users or 0,
        active_users=active_users or 0,
        open_sos_alerts=open_sos_alerts or 0,
        pending_reports=pending_reports or 0,
        verified_assistance_points=assistance_points or 0,
        active_railway_records=railway_records or 0,
    )


@router.get("/users", response_model=list[AdminUserRead])
async def admin_list_users(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    _: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> list[AdminUserRead]:
    result = await db.execute(
        select(User).order_by(User.created_at.desc()).offset(offset).limit(limit)
    )
    return list(result.scalars().all())


@router.patch("/users/{user_id}", response_model=AdminUserRead)
async def admin_update_user(
    user_id: UUID,
    payload: AdminUserUpdate,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> AdminUserRead:
    if user_id == admin.id and (
        payload.role != "admin" or not payload.is_active
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You cannot remove your own administrator access",
        )
    target = await db.scalar(
        select(User).where(User.id == user_id).with_for_update()
    )
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    if target.role == "admin" and target.is_active and (
        payload.role != "admin" or not payload.is_active
    ):
        active_admins = await db.scalars(
            select(User)
            .where(User.role == "admin", User.is_active.is_(True))
            .order_by(User.id)
            .with_for_update()
        )
        if len(list(active_admins.all())) <= 1:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="At least one active administrator must remain",
            )

    target.role = payload.role
    target.is_active = payload.is_active
    await db.commit()
    await db.refresh(target)
    return target


def serialize_admin_sos(alert: SafetyAlert, owner: User) -> AdminSOSAlertRead:
    return AdminSOSAlertRead(
        id=alert.id,
        user_id=owner.id,
        user_name=owner.name,
        user_email=owner.email,
        journey_id=alert.journey_id,
        alert_type=alert.alert_type,
        status=alert.status,
        admin_status=alert.admin_status,
        admin_note=alert.admin_note,
        description=alert.description,
        journey_snapshot=alert.journey_snapshot,
        latitude=alert.latitude,
        longitude=alert.longitude,
        location_captured_at=alert.location_captured_at,
        created_at=alert.created_at,
        admin_reviewed_at=alert.admin_reviewed_at,
        deliveries=[
            AdminSOSDeliveryRead(
                contact_name=delivery.contact_name,
                phone=delivery.phone,
                message_type=delivery.message_type,
                status=delivery.status,
                last_error=delivery.last_error,
                attempt_count=delivery.attempt_count,
            )
            for delivery in alert.deliveries
        ],
    )


@router.get("/sos-alerts", response_model=list[AdminSOSAlertRead])
async def admin_list_sos_alerts(
    alert_status: str | None = Query(default=None, alias="status", max_length=24),
    limit: int = Query(default=100, ge=1, le=500),
    _: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> list[AdminSOSAlertRead]:
    statement = (
        select(SafetyAlert, User)
        .join(User, User.id == SafetyAlert.user_id)
        .options(selectinload(SafetyAlert.deliveries))
    )
    if alert_status:
        statement = statement.where(SafetyAlert.admin_status == alert_status)
    result = await db.execute(
        statement.order_by(SafetyAlert.created_at.desc()).limit(limit)
    )
    return [
        serialize_admin_sos(alert, owner)
        for alert, owner in result.all()
    ]


@router.patch("/sos-alerts/{alert_id}", response_model=AdminSOSAlertRead)
async def admin_update_sos_alert(
    alert_id: UUID,
    payload: AdminSOSAlertUpdate,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> AdminSOSAlertRead:
    result = await db.execute(
        select(SafetyAlert, User)
        .join(User, User.id == SafetyAlert.user_id)
        .where(SafetyAlert.id == alert_id)
        .options(selectinload(SafetyAlert.deliveries))
        .with_for_update(of=SafetyAlert)
    )
    record = result.one_or_none()
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="SOS alert not found")
    alert, owner = record
    alert.admin_status = payload.admin_status
    alert.admin_note = payload.admin_note or None
    alert.admin_reviewed_by_id = admin.id
    alert.admin_reviewed_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(alert)
    await db.refresh(owner)
    return serialize_admin_sos(alert, owner)


def serialize_admin_report(
    report: CommunitySafetyReport,
    owner: User,
) -> AdminCommunityReportRead:
    return AdminCommunityReportRead(
        id=report.id,
        report_type=report.report_type,
        description=report.description,
        status=report.status,
        latitude=report.latitude,
        longitude=report.longitude,
        duplicate_of_id=report.duplicate_of_id,
        image_ids=[image.id for image in report.images],
        created_at=report.created_at,
        verified_at=report.verified_at,
        user_id=owner.id,
        user_name=owner.name,
        user_email=owner.email,
        moderator_note=report.moderator_note,
    )


@router.get("/community-reports", response_model=list[AdminCommunityReportRead])
async def admin_list_community_reports(
    report_status: str | None = Query(default=None, alias="status", max_length=24),
    limit: int = Query(default=100, ge=1, le=500),
    _: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> list[AdminCommunityReportRead]:
    statement = (
        select(CommunitySafetyReport, User)
        .join(User, User.id == CommunitySafetyReport.user_id)
        .options(selectinload(CommunitySafetyReport.images))
    )
    if report_status:
        statement = statement.where(CommunitySafetyReport.status == report_status)
    result = await db.execute(
        statement.order_by(CommunitySafetyReport.created_at.desc()).limit(limit)
    )
    return [
        serialize_admin_report(report, owner)
        for report, owner in result.all()
    ]


@router.patch(
    "/community-reports/{report_id}",
    response_model=AdminCommunityReportRead,
)
async def admin_review_community_report(
    report_id: UUID,
    payload: CommunitySafetyReportReview,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> AdminCommunityReportRead:
    report = await db.scalar(
        select(CommunitySafetyReport)
        .where(CommunitySafetyReport.id == report_id)
        .options(selectinload(CommunitySafetyReport.images))
        .with_for_update()
    )
    if report is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Community report not found",
        )
    if payload.duplicate_of_id is not None:
        if payload.duplicate_of_id == report.id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="A report cannot be marked as a duplicate of itself",
            )
        duplicate_target = await db.scalar(
            select(CommunitySafetyReport).where(
                CommunitySafetyReport.id == payload.duplicate_of_id,
                CommunitySafetyReport.status != "duplicate",
            )
        )
        if duplicate_target is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Original report not found",
            )

    report.status = payload.status
    report.duplicate_of_id = payload.duplicate_of_id
    report.moderator_note = payload.moderator_note or None
    report.verified_by_id = admin.id
    report.verified_at = datetime.now(UTC) if payload.status == "verified" else None
    owner = await db.get(User, report.user_id)
    if owner is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Report owner not found",
        )
    enqueue_notification(
        db,
        owner.id,
        "community_report_status",
        "Community report updated",
        f"Your {report.report_type.replace('_', ' ')} report is now {report.status.replace('_', ' ')}.",
        {"screen": "Notifications", "report_id": str(report.id)},
    )
    await db.commit()
    await db.refresh(report)
    return serialize_admin_report(report, owner)


@router.get(
    "/community-reports/{report_id}/images/{image_id}",
    response_class=Response,
)
async def admin_get_report_image(
    report_id: UUID,
    image_id: UUID,
    _: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> Response:
    image = await db.scalar(
        select(CommunitySafetyReportImage).where(
            CommunitySafetyReportImage.id == image_id,
            CommunitySafetyReportImage.report_id == report_id,
        )
    )
    if image is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report image not found")
    return Response(
        content=image.content,
        media_type=image.media_type,
        headers={
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/assistance-points", response_model=list[AssistancePointRead])
async def admin_list_assistance_points(
    _: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> list[AssistancePointRead]:
    result = await db.execute(
        select(VerifiedAssistancePoint).order_by(
            VerifiedAssistancePoint.is_active.desc(),
            VerifiedAssistancePoint.name,
        )
    )
    return list(result.scalars().all())


@router.post(
    "/assistance-points",
    response_model=AssistancePointRead,
    status_code=status.HTTP_201_CREATED,
)
async def admin_create_assistance_point(
    payload: AssistancePointCreate,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> AssistancePointRead:
    now = datetime.now(UTC)
    point = VerifiedAssistancePoint(
        **payload.model_dump(),
        created_by_id=admin.id,
        updated_by_id=admin.id,
        verified_at=now,
    )
    db.add(point)
    await db.commit()
    await db.refresh(point)
    return point


@router.patch("/assistance-points/{point_id}", response_model=AssistancePointRead)
async def admin_update_assistance_point(
    point_id: UUID,
    payload: AssistancePointUpdate,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> AssistancePointRead:
    point = await db.scalar(
        select(VerifiedAssistancePoint)
        .where(VerifiedAssistancePoint.id == point_id)
        .with_for_update()
    )
    if point is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assistance point not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(point, field, value)
    point.updated_by_id = admin.id
    point.updated_at = datetime.now(UTC)
    point.verified_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(point)
    return point


@router.delete("/assistance-points/{point_id}", status_code=status.HTTP_204_NO_CONTENT)
async def admin_delete_assistance_point(
    point_id: UUID,
    _: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> None:
    point = await db.get(VerifiedAssistancePoint, point_id)
    if point is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assistance point not found")
    await db.delete(point)
    await db.commit()


@router.get("/railway-assistance", response_model=list[RailwayAssistanceRead])
async def admin_list_railway_assistance(
    _: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> list[RailwayAssistanceRead]:
    result = await db.execute(
        select(RailwayAssistanceRecord).order_by(
            RailwayAssistanceRecord.is_active.desc(),
            RailwayAssistanceRecord.station_name,
            RailwayAssistanceRecord.title,
        )
    )
    return list(result.scalars().all())


@router.post(
    "/railway-assistance",
    response_model=RailwayAssistanceRead,
    status_code=status.HTTP_201_CREATED,
)
async def admin_create_railway_assistance(
    payload: RailwayAssistanceCreate,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> RailwayAssistanceRead:
    item = RailwayAssistanceRecord(
        **payload.model_dump(),
        created_by_id=admin.id,
        updated_by_id=admin.id,
    )
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return item


@router.patch(
    "/railway-assistance/{record_id}",
    response_model=RailwayAssistanceRead,
)
async def admin_update_railway_assistance(
    record_id: UUID,
    payload: RailwayAssistanceUpdate,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> RailwayAssistanceRead:
    item = await db.scalar(
        select(RailwayAssistanceRecord)
        .where(RailwayAssistanceRecord.id == record_id)
        .with_for_update()
    )
    if item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Railway assistance record not found",
        )
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(item, field, value)
    item.updated_by_id = admin.id
    item.updated_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(item)
    return item


@router.delete(
    "/railway-assistance/{record_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def admin_delete_railway_assistance(
    record_id: UUID,
    _: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> None:
    item = await db.get(RailwayAssistanceRecord, record_id)
    if item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Railway assistance record not found",
        )
    await db.delete(item)
    await db.commit()
