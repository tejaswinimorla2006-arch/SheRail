import hashlib
import math
from datetime import UTC, datetime, timedelta
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile, status
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.dependencies import get_current_admin, get_current_user
from app.models import (
    CommunitySafetyReport,
    CommunitySafetyReportImage,
    User,
    VerifiedAssistancePoint,
)
from app.notification_delivery import enqueue_notification
from app.schemas import (
    CommunitySafetyReportCreate,
    CommunitySafetyReportRead,
    CommunitySafetyReportReview,
    LocationSearchRequest,
    ModeratorAccessRead,
    NearbyPlaceRead,
)

router = APIRouter(prefix="/map", tags=["nearby help and safety map"])

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
MAX_MAP_RESULTS = 250
MAX_REPORT_IMAGES = 4
MAX_REPORT_IMAGE_BYTES = 5 * 1024 * 1024
MAX_REPORT_IMAGE_TOTAL_BYTES = 12 * 1024 * 1024


def distance_meters(lat1: float, lon1: float, lat2: float, lon2: float) -> int:
    earth_radius_m = 6_371_000
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    haversine = (
        math.sin(delta_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    )
    return round(earth_radius_m * 2 * math.atan2(math.sqrt(haversine), math.sqrt(1 - haversine)))


def require_location_consent(consent: bool) -> None:
    if not consent:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Explicit location consent is required for this map search",
        )


def moderator_allowed(user: User) -> bool:
    return user.is_active and user.role == "admin"


def place_category(tags: dict[str, str]) -> str | None:
    amenity = tags.get("amenity")
    if amenity == "police":
        return "police"
    if amenity in ("hospital", "clinic"):
        return "hospital"
    if amenity in ("fire_station", "shelter", "social_facility"):
        return "assistance"
    emergency = tags.get("emergency")
    if emergency in ("ambulance_station", "phone", "fire_station"):
        return "assistance"
    if tags.get("highway") == "emergency_access_point":
        return "assistance"
    return None


def osm_query(latitude: float, longitude: float, radius_m: int) -> str:
    return f"""
[out:json][timeout:18];
(
  node(around:{radius_m},{latitude},{longitude})["amenity"~"^(police|hospital|clinic|fire_station|shelter|social_facility)$"];
  way(around:{radius_m},{latitude},{longitude})["amenity"~"^(police|hospital|clinic|fire_station|shelter|social_facility)$"];
  relation(around:{radius_m},{latitude},{longitude})["amenity"~"^(police|hospital|clinic|fire_station|shelter|social_facility)$"];
  node(around:{radius_m},{latitude},{longitude})["emergency"~"^(ambulance_station|phone|fire_station)$"];
  way(around:{radius_m},{latitude},{longitude})["emergency"~"^(ambulance_station|phone|fire_station)$"];
  relation(around:{radius_m},{latitude},{longitude})["emergency"~"^(ambulance_station|phone|fire_station)$"];
  node(around:{radius_m},{latitude},{longitude})["highway"="emergency_access_point"];
  way(around:{radius_m},{latitude},{longitude})["highway"="emergency_access_point"];
);
out center tags;
"""


def format_place(element: dict, latitude: float, longitude: float) -> NearbyPlaceRead | None:
    tags = element.get("tags")
    if not isinstance(tags, dict):
        return None
    category = place_category(tags)
    coordinates = element.get("center", element)
    try:
        place_latitude = float(coordinates["lat"])
        place_longitude = float(coordinates["lon"])
        element_id = int(element["id"])
        element_type = str(element["type"])
    except (KeyError, TypeError, ValueError):
        return None
    if not -90 <= place_latitude <= 90 or not -180 <= place_longitude <= 180:
        return None
    if category is None:
        return None

    name = tags.get("name") or tags.get("official_name") or f"Unnamed {category} location"
    address_parts = [
        " ".join(part for part in (tags.get("addr:housenumber"), tags.get("addr:street")) if part),
        tags.get("addr:city"),
        tags.get("addr:postcode"),
    ]
    address = ", ".join(part for part in address_parts if part) or None
    return NearbyPlaceRead(
        id=f"{element_type}/{element_id}",
        name=name,
        category=category,
        latitude=place_latitude,
        longitude=place_longitude,
        distance_m=distance_meters(latitude, longitude, place_latitude, place_longitude),
        address=address,
        osm_url=f"https://www.openstreetmap.org/{element_type}/{element_id}",
        source="openstreetmap",
    )


def report_read(
    report: CommunitySafetyReport,
    latitude: float | None = None,
    longitude: float | None = None,
) -> CommunitySafetyReportRead:
    return CommunitySafetyReportRead(
        id=report.id,
        report_type=report.report_type,
        description=report.description,
        status=report.status,
        latitude=report.latitude,
        longitude=report.longitude,
        duplicate_of_id=report.duplicate_of_id,
        image_ids=[image.id for image in report.images],
        distance_m=(
            distance_meters(latitude, longitude, report.latitude, report.longitude)
            if latitude is not None and longitude is not None
            else None
        ),
        created_at=report.created_at,
        verified_at=report.verified_at,
    )


@router.post("/nearby", response_model=list[NearbyPlaceRead])
async def nearby_places(
    request: LocationSearchRequest,
    _: User = Depends(get_current_user),
) -> list[NearbyPlaceRead]:
    require_location_consent(request.location_consent)
    headers = {"User-Agent": "SheRail safety map (OpenStreetMap data)"}
    try:
        async with httpx.AsyncClient(timeout=22) as client:
            response = await client.post(
                OVERPASS_URL,
                data={"data": osm_query(request.latitude, request.longitude, request.radius_m)},
                headers=headers,
            )
            response.raise_for_status()
    except httpx.HTTPStatusError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="OpenStreetMap place search is temporarily unavailable",
        ) from error
    except httpx.RequestError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not reach OpenStreetMap. Try the search again later.",
        ) from error

    try:
        elements = response.json().get("elements")
    except (ValueError, AttributeError) as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="OpenStreetMap returned an unreadable place response",
        ) from error
    if not isinstance(elements, list):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="OpenStreetMap returned an invalid place response",
        )

    places = [
        place
        for element in elements
        if isinstance(element, dict)
        if (place := format_place(element, request.latitude, request.longitude)) is not None
        and place.distance_m <= request.radius_m
    ]
    places.sort(key=lambda place: (place.distance_m, place.name.casefold()))
    return places[:MAX_MAP_RESULTS]


@router.post("/reports/search", response_model=list[CommunitySafetyReportRead])
async def search_verified_reports(
    request: LocationSearchRequest,
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[CommunitySafetyReportRead]:
    require_location_consent(request.location_consent)
    latitude_delta = request.radius_m / 111_000
    longitude_scale = max(abs(math.cos(math.radians(request.latitude))), 0.01)
    longitude_delta = min(180, request.radius_m / (111_000 * longitude_scale))
    result = await db.execute(
        select(CommunitySafetyReport)
        .options(selectinload(CommunitySafetyReport.images))
        .where(
            CommunitySafetyReport.status == "verified",
            CommunitySafetyReport.verified_at.is_not(None),
            CommunitySafetyReport.latitude.between(
                max(-90, request.latitude - latitude_delta),
                min(90, request.latitude + latitude_delta),
            ),
            CommunitySafetyReport.longitude.between(
                max(-180, request.longitude - longitude_delta),
                min(180, request.longitude + longitude_delta),
            ),
        )
        .order_by(CommunitySafetyReport.verified_at.desc())
        .limit(MAX_MAP_RESULTS)
    )
    reports = [
        report_read(item, request.latitude, request.longitude)
        for item in result.scalars().all()
    ]
    return [item for item in reports if item.distance_m is not None and item.distance_m <= request.radius_m]


@router.post(
    "/reports",
    response_model=CommunitySafetyReportRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_community_report(
    payload: CommunitySafetyReportCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CommunitySafetyReportRead:
    return await persist_community_report(payload, [], user, db)


@router.post(
    "/reports/submit",
    response_model=CommunitySafetyReportRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_community_report_with_images(
    report_type: str = Form(...),
    description: str = Form(...),
    latitude: float = Form(...),
    longitude: float = Form(...),
    location_consent: bool = Form(...),
    images: list[UploadFile] = File(default=[]),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CommunitySafetyReportRead:
    try:
        payload = CommunitySafetyReportCreate.model_validate(
            {
                "report_type": report_type,
                "description": description,
                "latitude": latitude,
                "longitude": longitude,
                "location_consent": location_consent,
            }
        )
    except ValidationError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=error.errors(include_url=False),
        ) from error
    return await persist_community_report(payload, images, user, db)


async def persist_community_report(
    payload: CommunitySafetyReportCreate,
    uploads: list[UploadFile],
    user: User,
    db: AsyncSession,
) -> CommunitySafetyReportRead:
    require_location_consent(payload.location_consent)
    if len(uploads) > MAX_REPORT_IMAGES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"You can attach up to {MAX_REPORT_IMAGES} images",
        )

    image_contents: list[tuple[str, str, bytes]] = []
    total_bytes = 0
    seen_hashes = set()
    for upload in uploads:
        content = await upload.read(MAX_REPORT_IMAGE_BYTES + 1)
        if not content:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Empty report images are not allowed",
            )
        if len(content) > MAX_REPORT_IMAGE_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail="Each report image must be 5 MB or smaller",
            )
        total_bytes += len(content)
        if total_bytes > MAX_REPORT_IMAGE_TOTAL_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail="Report images must total 12 MB or less",
            )

        media_type = detect_image_type(content)
        if media_type is None:
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail="Report attachments must be JPEG, PNG, or WebP images",
            )
        sha256 = hashlib.sha256(content).hexdigest()
        if sha256 in seen_hashes:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="The same image cannot be attached more than once",
            )
        seen_hashes.add(sha256)
        image_contents.append((media_type, sha256, content))

    submitted_since = datetime.now(UTC) - timedelta(hours=1)
    recent_count = await db.scalar(
        select(func.count(CommunitySafetyReport.id)).where(
            CommunitySafetyReport.user_id == user.id,
            CommunitySafetyReport.created_at >= submitted_since,
        )
    )
    if (recent_count or 0) >= 5:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="You have reached the report limit. Try again later.",
        )

    duplicate = await find_possible_duplicate(payload, db)
    report = CommunitySafetyReport(
        user_id=user.id,
        report_type=payload.report_type.value,
        description=payload.description,
        latitude=payload.latitude,
        longitude=payload.longitude,
        location_consented_at=datetime.now(UTC),
        status="duplicate" if duplicate else "pending",
        duplicate_of_id=duplicate.id if duplicate else None,
    )
    for media_type, sha256, content in image_contents:
        report.images.append(
            CommunitySafetyReportImage(
                media_type=media_type,
                sha256=sha256,
                content=content,
            )
        )
    db.add(report)
    admins = await db.scalars(
        select(User.id).where(User.role == "admin", User.is_active.is_(True))
    )
    for admin_id in admins.all():
        enqueue_notification(
            db,
            admin_id,
            "community_report_new",
            "New community safety report",
            "A community report is waiting for review.",
            {"screen": "Notifications", "report_id": str(report.id)},
        )
    await db.commit()
    await db.refresh(report)
    return report_read(report)


def detect_image_type(content: bytes) -> str | None:
    if content.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if len(content) >= 12 and content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return "image/webp"
    return None


async def find_possible_duplicate(
    payload: CommunitySafetyReportCreate,
    db: AsyncSession,
) -> CommunitySafetyReport | None:
    latitude_delta = 100 / 111_000
    longitude_scale = max(abs(math.cos(math.radians(payload.latitude))), 0.01)
    longitude_delta = min(180, 100 / (111_000 * longitude_scale))
    result = await db.execute(
        select(CommunitySafetyReport)
        .where(
            CommunitySafetyReport.report_type == payload.report_type.value,
            CommunitySafetyReport.status.in_(("pending", "under_review", "verified")),
            CommunitySafetyReport.created_at >= datetime.now(UTC) - timedelta(hours=24),
            CommunitySafetyReport.latitude.between(
                max(-90, payload.latitude - latitude_delta),
                min(90, payload.latitude + latitude_delta),
            ),
            CommunitySafetyReport.longitude.between(
                max(-180, payload.longitude - longitude_delta),
                min(180, payload.longitude + longitude_delta),
            ),
        )
        .order_by(CommunitySafetyReport.created_at)
        .limit(50)
    )
    for report in result.scalars().all():
        if distance_meters(
            payload.latitude,
            payload.longitude,
            report.latitude,
            report.longitude,
        ) <= 100:
            return report
    return None


@router.get("/reports/mine", response_model=list[CommunitySafetyReportRead])
async def list_my_community_reports(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[CommunitySafetyReportRead]:
    result = await db.execute(
        select(CommunitySafetyReport)
        .options(selectinload(CommunitySafetyReport.images))
        .where(CommunitySafetyReport.user_id == user.id)
        .order_by(CommunitySafetyReport.created_at.desc())
        .limit(100)
    )
    return [report_read(report) for report in result.scalars().all()]


@router.post(
    "/assistance-points/nearby",
    response_model=list[NearbyPlaceRead],
)
async def nearby_verified_assistance_points(
    request: LocationSearchRequest,
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[NearbyPlaceRead]:
    require_location_consent(request.location_consent)
    latitude_delta = request.radius_m / 111_000
    longitude_scale = max(abs(math.cos(math.radians(request.latitude))), 0.01)
    longitude_delta = min(180, request.radius_m / (111_000 * longitude_scale))
    result = await db.execute(
        select(VerifiedAssistancePoint).where(
            VerifiedAssistancePoint.is_active.is_(True),
            VerifiedAssistancePoint.latitude.between(
                max(-90, request.latitude - latitude_delta),
                min(90, request.latitude + latitude_delta),
            ),
            VerifiedAssistancePoint.longitude.between(
                max(-180, request.longitude - longitude_delta),
                min(180, request.longitude + longitude_delta),
            ),
        )
    )
    category_map = {
        "hospital": "hospital",
        "clinic": "hospital",
        "police": "police",
    }
    points = []
    for point in result.scalars().all():
        distance = distance_meters(
            request.latitude,
            request.longitude,
            point.latitude,
            point.longitude,
        )
        if distance > request.radius_m:
            continue
        points.append(
            NearbyPlaceRead(
                id=f"sherail:{point.id}",
                name=point.name,
                category=category_map.get(point.category, "assistance"),
                latitude=point.latitude,
                longitude=point.longitude,
                distance_m=distance,
                address=point.address,
                phone=point.phone,
                description=point.description,
                source="sherail_verified",
            )
        )
    points.sort(key=lambda point: (point.distance_m, point.name.casefold()))
    return points[:MAX_MAP_RESULTS]


@router.get("/reports/{report_id}/images/{image_id}", response_class=Response)
async def get_community_report_image(
    report_id: UUID,
    image_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    record = await db.execute(
        select(CommunitySafetyReport, CommunitySafetyReportImage)
        .join(
            CommunitySafetyReportImage,
            CommunitySafetyReportImage.report_id == CommunitySafetyReport.id,
        )
        .where(
            CommunitySafetyReport.id == report_id,
            CommunitySafetyReportImage.id == image_id,
        )
    )
    pair = record.one_or_none()
    if pair is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report image not found")
    report, image = pair
    if report.user_id != user.id and user.role != "admin":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report image not found")
    return Response(
        content=image.content,
        media_type=image.media_type,
        headers={
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/moderation/access", response_model=ModeratorAccessRead)
async def moderation_access(
    user: User = Depends(get_current_user),
) -> ModeratorAccessRead:
    return ModeratorAccessRead(can_moderate=moderator_allowed(user))


@router.get("/moderation/reports", response_model=list[CommunitySafetyReportRead])
async def pending_reports(
    user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> list[CommunitySafetyReportRead]:
    result = await db.execute(
        select(CommunitySafetyReport)
        .options(selectinload(CommunitySafetyReport.images))
        .where(CommunitySafetyReport.status.in_(("pending", "under_review")))
        .order_by(CommunitySafetyReport.created_at)
        .limit(100)
    )
    return [report_read(item) for item in result.scalars().all()]


@router.patch("/moderation/reports/{report_id}", response_model=CommunitySafetyReportRead)
async def review_report(
    report_id: UUID,
    payload: CommunitySafetyReportReview,
    user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> CommunitySafetyReportRead:
    report = await db.scalar(
        select(CommunitySafetyReport)
        .where(CommunitySafetyReport.id == report_id)
        .options(selectinload(CommunitySafetyReport.images))
        .with_for_update()
    )
    if report is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Community report not found")
    if report.status not in ("pending", "under_review"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This community report has already been reviewed",
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
    report.verified_by_id = user.id
    report.verified_at = datetime.now(UTC) if payload.status == "verified" else None
    owner = await db.get(User, report.user_id)
    if owner is not None:
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
    return report_read(report)
