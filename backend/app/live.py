import asyncio
import time
from dataclasses import dataclass
from uuid import UUID

import jwt
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import ValidationError
from sqlalchemy import select

from app.config import get_settings
from app.database import SessionFactory
from app.models import Journey, JourneyLocation, JourneyShare, User
from app.schemas import JourneyStatus, WebSocketLocationUpdate
from app.safety import evaluate_location_safety

router = APIRouter(tags=["live journey locations"])


@dataclass
class ActiveConnection:
    websocket: WebSocket
    user_id: UUID
    token_expires_at: float


class ConnectionManager:
    def __init__(self) -> None:
        self._connections: dict[UUID, list[ActiveConnection]] = {}
        self._send_locks: dict[UUID, asyncio.Lock] = {}

    async def connect(
        self,
        journey_id: UUID,
        websocket: WebSocket,
        user_id: UUID,
        token_expires_at: float,
    ) -> None:
        self._connections.setdefault(journey_id, []).append(
            ActiveConnection(websocket, user_id, token_expires_at)
        )

    def disconnect(self, journey_id: UUID, websocket: WebSocket) -> None:
        connections = self._connections.get(journey_id, [])
        self._connections[journey_id] = [
            item for item in connections if item.websocket is not websocket
        ]
        if not self._connections[journey_id]:
            self._connections.pop(journey_id, None)
            self._send_locks.pop(journey_id, None)

    async def close_connections(
        self,
        journey_id: UUID,
        user_ids: set[UUID],
        event: dict,
    ) -> None:
        lock = self._send_locks.setdefault(journey_id, asyncio.Lock())
        stale: list[WebSocket] = []
        async with lock:
            for connection in tuple(self._connections.get(journey_id, [])):
                if connection.user_id not in user_ids:
                    continue
                try:
                    await connection.websocket.send_json(event)
                    await connection.websocket.close(code=4403)
                except (OSError, RuntimeError, WebSocketDisconnect):
                    pass
                stale.append(connection.websocket)
        for websocket in stale:
            self.disconnect(journey_id, websocket)

    async def broadcast(
        self,
        journey_id: UUID,
        message: dict,
        journey_owner_id: UUID,
        recipient_ids: set[UUID],
    ) -> None:
        lock = self._send_locks.setdefault(journey_id, asyncio.Lock())
        now = time.time()
        stale: list[WebSocket] = []
        async with lock:
            for connection in tuple(self._connections.get(journey_id, [])):
                allowed = (
                    connection.user_id == journey_owner_id
                    or connection.user_id in recipient_ids
                )
                if not allowed or connection.token_expires_at <= now:
                    if connection.token_expires_at <= now:
                        stale.append(connection.websocket)
                        try:
                            await connection.websocket.close(code=4401)
                        except (OSError, RuntimeError):
                            pass
                    continue
                try:
                    await connection.websocket.send_json(message)
                except (OSError, RuntimeError, WebSocketDisconnect):
                    stale.append(connection.websocket)
        for websocket in stale:
            self.disconnect(journey_id, websocket)

    async def send_to_users(
        self,
        journey_id: UUID,
        user_ids: set[UUID],
        message: dict,
    ) -> None:
        lock = self._send_locks.setdefault(journey_id, asyncio.Lock())
        now = time.time()
        stale: list[WebSocket] = []
        async with lock:
            for connection in tuple(self._connections.get(journey_id, [])):
                if connection.user_id not in user_ids:
                    continue
                if connection.token_expires_at <= now:
                    stale.append(connection.websocket)
                    try:
                        await connection.websocket.close(code=4401)
                    except (OSError, RuntimeError):
                        pass
                    continue
                try:
                    await connection.websocket.send_json(message)
                except (OSError, RuntimeError, WebSocketDisconnect):
                    stale.append(connection.websocket)
        for websocket in stale:
            self.disconnect(journey_id, websocket)


connection_manager = ConnectionManager()


async def authenticate_access_token(token: str) -> tuple[User | None, float | None]:
    try:
        payload = jwt.decode(
            token,
            get_settings().jwt_secret_key.get_secret_value(),
            algorithms=["HS256"],
        )
        user_id = UUID(payload["sub"])
        expires_at = float(payload["exp"])
    except (jwt.InvalidTokenError, KeyError, TypeError, ValueError):
        return None, None

    async with SessionFactory() as db:
        user = await db.get(User, user_id)
        return user, expires_at


@router.websocket("/ws/journeys/{journey_id}")
async def journey_location_socket(websocket: WebSocket, journey_id: UUID) -> None:
    await websocket.accept()
    try:
        credentials = await asyncio.wait_for(websocket.receive_json(), timeout=10)
    except (TimeoutError, WebSocketDisconnect):
        await websocket.close(code=4401, reason="Authenticate to join this journey")
        return

    if not isinstance(credentials, dict) or credentials.get("type") != "authenticate":
        await websocket.close(code=4401, reason="Authentication required")
        return

    token = credentials.get("access_token")
    if not isinstance(token, str):
        await websocket.close(code=4401, reason="Authentication required")
        return

    user, token_expires_at = await authenticate_access_token(token)
    if user is None or token_expires_at is None:
        await websocket.close(code=4401, reason="Invalid or expired access token")
        return

    async with SessionFactory() as db:
        journey_result = await db.execute(
            select(Journey).where(Journey.id == journey_id)
        )
        journey = journey_result.scalar_one_or_none()
        if journey is None or journey.status != JourneyStatus.ACTIVE.value:
            await websocket.close(code=4404, reason="Active journey not found")
            return

        is_owner = journey.user_id == user.id
        if not is_owner:
            share_result = await db.execute(
                select(JourneyShare.id).where(
                    JourneyShare.journey_id == journey.id,
                    JourneyShare.recipient_user_id == user.id,
                )
            )
            if (
                not journey.sharing_enabled
                or not journey.location_recording_enabled
                or share_result.scalar_one_or_none() is None
            ):
                await websocket.close(code=4403, reason="This journey was not shared with you")
                return

        tracking_consent = credentials.get("tracking_consent") is True
        if tracking_consent and (
            not is_owner or not journey.location_recording_enabled
        ):
            await websocket.close(code=4403, reason="Location recording is not enabled")
            return

        await db.commit()
        await connection_manager.connect(
            journey.id,
            websocket,
            user.id,
            token_expires_at,
        )
        await websocket.send_json(
            {
                "type": "authenticated",
                "journey_id": str(journey.id),
                "role": "owner" if is_owner else "viewer",
            }
        )

        latest_result = await db.execute(
            select(JourneyLocation)
            .where(JourneyLocation.journey_id == journey.id)
            .order_by(JourneyLocation.captured_at.desc())
            .limit(1)
        )
        latest = latest_result.scalar_one_or_none()
        if latest is not None:
            await websocket.send_json(
                {
                    "type": "location",
                    "journey_id": str(journey.id),
                    "location": {
                        "latitude": latest.latitude,
                        "longitude": latest.longitude,
                        "accuracy_m": latest.accuracy_m,
                        "captured_at": latest.captured_at.isoformat(),
                        "received_at": latest.received_at.isoformat(),
                    },
                }
            )

        try:
            while True:
                if token_expires_at <= time.time():
                    await websocket.close(code=4401, reason="Access token expired")
                    break

                message = await websocket.receive_json()
                if not isinstance(message, dict) or message.get("type") != "location":
                    await websocket.send_json(
                        {"type": "error", "detail": "Unsupported journey message"}
                    )
                    continue
                if not is_owner or not tracking_consent:
                    await websocket.send_json(
                        {"type": "error", "detail": "This connection cannot submit location updates"}
                    )
                    continue

                try:
                    location = WebSocketLocationUpdate.model_validate(message)
                except ValidationError as error:
                    await websocket.send_json(
                        {"type": "error", "detail": error.errors(include_url=False)}
                    )
                    continue

                fresh_journey_result = await db.execute(
                    select(Journey)
                    .where(Journey.id == journey.id)
                    .execution_options(populate_existing=True)
                    .with_for_update()
                )
                fresh_journey = fresh_journey_result.scalar_one_or_none()
                if (
                    fresh_journey is None
                    or fresh_journey.status != JourneyStatus.ACTIVE.value
                    or not fresh_journey.location_recording_enabled
                ):
                    await websocket.close(code=4409, reason="Journey tracking is paused or ended")
                    break

                previous_point = await db.scalar(
                    select(JourneyLocation)
                    .where(JourneyLocation.journey_id == journey.id)
                    .order_by(JourneyLocation.captured_at.desc())
                    .limit(1)
                )
                point = JourneyLocation(
                    journey_id=journey.id,
                    latitude=location.latitude,
                    longitude=location.longitude,
                    accuracy_m=location.accuracy_m,
                    captured_at=location.captured_at,
                )
                db.add(point)
                await db.flush()
                safety_events = await evaluate_location_safety(
                    db,
                    fresh_journey,
                    point,
                    previous_point,
                )
                await db.commit()
                await db.refresh(point)
                for safety_event in safety_events:
                    await connection_manager.broadcast(
                        journey.id,
                        {
                            "type": "safety_event",
                            "event": {
                                "id": str(safety_event.id),
                                "event_type": safety_event.event_type,
                                "details": safety_event.details,
                                "occurred_at": safety_event.occurred_at.isoformat(),
                            },
                        },
                        journey_owner_id=journey.user_id,
                        recipient_ids=set(),
                    )

                recipient_result = await db.execute(
                    select(JourneyShare.recipient_user_id).where(
                        JourneyShare.journey_id == journey.id
                    )
                ) if (
                    fresh_journey.sharing_enabled
                    and fresh_journey.location_recording_enabled
                ) else None
                recipient_ids = (
                    set(recipient_result.scalars().all())
                    if recipient_result is not None
                    else set()
                )
                await connection_manager.broadcast(
                    journey.id,
                    {
                        "type": "location",
                        "journey_id": str(journey.id),
                        "location": {
                            "latitude": point.latitude,
                            "longitude": point.longitude,
                            "accuracy_m": point.accuracy_m,
                            "captured_at": point.captured_at.isoformat(),
                            "received_at": point.received_at.isoformat(),
                        },
                    },
                    journey_owner_id=journey.user_id,
                    recipient_ids=recipient_ids,
                )
        except WebSocketDisconnect:
            pass
        finally:
            connection_manager.disconnect(journey.id, websocket)
