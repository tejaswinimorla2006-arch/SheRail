import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy import func, select

from app.models import Journey, SafetyAlert, SafetyAlertDelivery, SafetyEvent, User


async def register(client, email):
    response = await client.post(
        "/api/v1/auth/register",
        json={
            "name": email.split("@")[0],
            "email": email,
            "password": secrets.token_urlsafe(16),
        },
    )
    assert response.status_code == 201
    return response.json()["user"], {
        "Authorization": f"Bearer {response.json()['access_token']}"
    }


async def create_active_checkin_journey(client, headers):
    created = await client.post(
        "/api/v1/journeys",
        headers=headers,
        json={"transport_mode": "walking"},
    )
    journey_id = created.json()["id"]
    started = await client.post(
        f"/api/v1/journeys/{journey_id}/start",
        headers=headers,
        json={"consent": True},
    )
    assert started.status_code == 200
    configured = await client.patch(
        f"/api/v1/journeys/{journey_id}/safety",
        headers=headers,
        json={
            "consent": True,
            "checkin_interval_minutes": 5,
            "checkin_grace_minutes": 1,
            "route_deviation_enabled": False,
            "route_deviation_threshold_m": 250,
            "long_stop_enabled": False,
            "long_stop_minutes": 10,
            "stop_radius_m": 50,
        },
    )
    assert configured.status_code == 200
    return journey_id, configured.json()


@pytest.mark.asyncio
async def test_journey_lifecycle_safety_checkin_and_owner_scoping(client):
    owner, owner_headers = await register(client, "journey-owner@example.com")
    _, other_headers = await register(client, "journey-other@example.com")
    created = await client.post(
        "/api/v1/journeys",
        headers=owner_headers,
        json={
            "transport_mode": "train",
            "origin": "Central",
            "destination": "North",
            "transport_details": {"train_number": "SR42"},
        },
    )
    assert created.status_code == 201
    journey_id = created.json()["id"]
    assert created.json()["user_id"] == owner["id"]

    foreign = await client.get(f"/api/v1/journeys/{journey_id}", headers=other_headers)
    assert foreign.status_code == 404
    foreign_checkin = await client.post(
        f"/api/v1/journeys/{journey_id}/check-in",
        headers=other_headers,
    )
    assert foreign_checkin.status_code == 404

    no_consent = await client.post(
        f"/api/v1/journeys/{journey_id}/start",
        headers=owner_headers,
        json={"consent": False},
    )
    assert no_consent.status_code == 403
    started = await client.post(
        f"/api/v1/journeys/{journey_id}/start",
        headers=owner_headers,
        json={"consent": True},
    )
    assert started.status_code == 200
    assert started.json()["status"] == "active"
    configured = await client.patch(
        f"/api/v1/journeys/{journey_id}/safety",
        headers=owner_headers,
        json={
            "consent": True,
            "checkin_interval_minutes": 5,
            "checkin_grace_minutes": 2,
            "route_deviation_enabled": False,
            "route_deviation_threshold_m": 250,
            "long_stop_enabled": False,
            "long_stop_minutes": 10,
            "stop_radius_m": 50,
        },
    )
    assert configured.status_code == 200
    checked_in = await client.post(
        f"/api/v1/journeys/{journey_id}/check-in",
        headers=owner_headers,
    )
    assert checked_in.status_code == 200
    assert checked_in.json()["checkin_due_at"] is not None

    paused = await client.post(
        f"/api/v1/journeys/{journey_id}/pause",
        headers=owner_headers,
    )
    assert paused.status_code == 200
    resumed = await client.post(
        f"/api/v1/journeys/{journey_id}/resume",
        headers=owner_headers,
        json={"consent": True},
    )
    assert resumed.status_code == 200
    ended = await client.post(
        f"/api/v1/journeys/{journey_id}/end",
        headers=owner_headers,
    )
    assert ended.status_code == 200
    assert ended.json()["status"] == "completed"


@pytest.mark.asyncio
async def test_safety_buddy_invitation_and_journey_sharing_require_explicit_consent(client):
    owner, owner_headers = await register(client, "buddy-owner@example.com")
    buddy, buddy_headers = await register(client, "buddy-recipient@example.com")
    invite = await client.post(
        "/api/v1/safety-buddies/invitations",
        headers=owner_headers,
        json={"email": "buddy-recipient@example.com"},
    )
    assert invite.status_code == 201
    invitation_id = invite.json()["id"]
    accepted = await client.post(
        f"/api/v1/safety-buddies/invitations/{invitation_id}/respond",
        headers=buddy_headers,
        json={"accept": True},
    )
    assert accepted.status_code == 200
    assert accepted.json()["status"] == "accepted"

    journey = await client.post(
        "/api/v1/journeys",
        headers=owner_headers,
        json={"transport_mode": "walking"},
    )
    journey_id = journey.json()["id"]
    no_consent = await client.post(
        f"/api/v1/safety-buddies/{buddy['id']}/journeys/{journey_id}",
        headers=owner_headers,
        json={"location_consent": False},
    )
    assert no_consent.status_code == 403
    not_started = await client.post(
        f"/api/v1/safety-buddies/{buddy['id']}/journeys/{journey_id}",
        headers=owner_headers,
        json={"location_consent": True},
    )
    assert not_started.status_code == 409

    started = await client.post(
        f"/api/v1/journeys/{journey_id}/start",
        headers=owner_headers,
        json={"consent": True},
    )
    assert started.status_code == 200
    shared = await client.post(
        f"/api/v1/safety-buddies/{buddy['id']}/journeys/{journey_id}",
        headers=owner_headers,
        json={"location_consent": True},
    )
    assert shared.status_code == 201
    recipient_view = await client.get(
        "/api/v1/journeys/shared-with-me",
        headers=buddy_headers,
    )
    assert [item["id"] for item in recipient_view.json()] == [journey_id]

    revoked = await client.patch(
        f"/api/v1/journeys/{journey_id}/tracking",
        headers=owner_headers,
        json={"consent": False},
    )
    assert revoked.status_code == 200
    assert (await client.get(
        "/api/v1/journeys/shared-with-me",
        headers=buddy_headers,
    )).json() == []


@pytest.mark.asyncio
async def test_sos_location_requires_consent_and_alerts_are_owner_scoped(client):
    _, owner_headers = await register(client, "sos-owner@example.com")
    _, other_headers = await register(client, "sos-other@example.com")
    invalid = await client.post(
        "/api/v1/safety/alerts/sos",
        headers=owner_headers,
        json={
            "share_location": False,
            "latitude": 12.9,
            "longitude": 77.5,
            "location_captured_at": "2026-11-16T10:00:00Z",
        },
    )
    assert invalid.status_code == 422
    created = await client.post(
        "/api/v1/safety/alerts/sos",
        headers=owner_headers,
        json={"share_location": False},
    )
    assert created.status_code == 201
    assert created.json()["latitude"] is None
    foreign = await client.get(
        f"/api/v1/safety/alerts/{created.json()['id']}",
        headers=other_headers,
    )
    assert foreign.status_code == 404


@pytest.mark.asyncio
async def test_checkin_is_idempotent_and_schedules_next_server_deadline(client, db_session):
    _, headers = await register(client, "checkin-idempotent@example.com")
    journey_id, configured = await create_active_checkin_journey(client, headers)
    configured_due = datetime.fromisoformat(configured["checkin_due_at"].replace("Z", "+00:00"))
    if configured_due.tzinfo is None:
        configured_due = configured_due.replace(tzinfo=UTC)
    assert configured_due > datetime.now(UTC)

    request_headers = {**headers, "Idempotency-Key": f"due:{configured['checkin_due_at']}"}
    first = await client.post(
        f"/api/v1/journeys/{journey_id}/check-in",
        headers=request_headers,
    )
    retry = await client.post(
        f"/api/v1/journeys/{journey_id}/check-in",
        headers=request_headers,
    )
    assert first.status_code == retry.status_code == 200
    assert first.json()["checkin_due_at"] == retry.json()["checkin_due_at"]

    event_count = await db_session.scalar(
        select(func.count()).select_from(SafetyEvent).where(
            SafetyEvent.journey_id == UUID(journey_id),
            SafetyEvent.event_type == "checkin_completed",
        )
    )
    assert event_count == 1


@pytest.mark.asyncio
async def test_missed_checkin_escalates_once_and_keeps_delivery_pending(
    client,
    db_session,
    test_sessions,
    monkeypatch,
):
    import app.safety as safety_tasks

    _, headers = await register(client, "missed-checkin@example.com")
    contact = await client.post(
        "/api/v1/users/me/emergency-contacts",
        headers=headers,
        json={
            "name": "Trusted contact",
            "phone": "+15551234567",
            "relationship": "Friend",
            "is_primary": True,
        },
    )
    assert contact.status_code == 201
    journey_id, _ = await create_active_checkin_journey(client, headers)
    journey = await db_session.scalar(
        select(Journey).where(Journey.id == UUID(journey_id))
    )
    journey.checkin_due_at = datetime.now(UTC) - timedelta(seconds=30)
    await db_session.commit()
    monkeypatch.setattr(safety_tasks, "SessionFactory", test_sessions)

    await safety_tasks.process_missed_checkins()
    before_grace = await db_session.scalar(
        select(func.count()).select_from(SafetyEvent).where(
            SafetyEvent.journey_id == UUID(journey_id),
            SafetyEvent.event_type == "missed_checkin",
        )
    )
    assert before_grace == 0

    journey.checkin_due_at = datetime.now(UTC) - timedelta(minutes=10)
    await db_session.commit()
    await safety_tasks.process_missed_checkins()

    missed_events = list((await db_session.scalars(
        select(SafetyEvent).where(
            SafetyEvent.journey_id == UUID(journey_id),
            SafetyEvent.event_type == "missed_checkin",
        )
    )).all())
    alerts = list((await db_session.scalars(
        select(SafetyAlert).where(
            SafetyAlert.journey_id == UUID(journey_id),
            SafetyAlert.alert_type == "missed_checkin",
        )
    )).all())
    deliveries = list((await db_session.scalars(
        select(SafetyAlertDelivery).where(
            SafetyAlertDelivery.alert_id == alerts[0].id,
        )
    )).all())

    assert len(missed_events) == len(alerts) == 1
    assert alerts[0].status == "pending"
    assert len(deliveries) == 1
    assert deliveries[0].status == "pending"
    assert await db_session.scalar(
        select(Journey.checkin_due_at).where(Journey.id == UUID(journey_id))
    ) is None


@pytest.mark.asyncio
async def test_sos_request_id_prevents_duplicate_alert_creation(client, db_session):
    user, headers = await register(client, "sos-idempotent@example.com")
    payload = {
        "share_location": False,
        "request_id": "00000000-0000-4000-8000-000000000001",
    }
    first = await client.post("/api/v1/safety/alerts/sos", headers=headers, json=payload)
    retry = await client.post("/api/v1/safety/alerts/sos", headers=headers, json=payload)

    assert first.status_code == 201
    assert retry.status_code == 200
    assert first.json()["id"] == retry.json()["id"]
    assert first.json()["status"] == "failed"
    alert_count = await db_session.scalar(
        select(func.count()).select_from(SafetyAlert).where(
            SafetyAlert.user_id == UUID(user["id"]),
            SafetyAlert.alert_type == "sos",
        )
    )
    event_count = await db_session.scalar(
        select(func.count()).select_from(SafetyEvent).where(
            SafetyEvent.user_id == UUID(user["id"]),
            SafetyEvent.event_type == "sos",
        )
    )
    assert alert_count == event_count == 1


@pytest.mark.asyncio
async def test_railway_assistance_requires_admin_to_manage_and_is_optional_for_users(
    client,
    db_session,
):
    admin, admin_headers = await register(client, "rail-admin@example.com")
    _, user_headers = await register(client, "rail-user@example.com")
    regular_create = await client.post(
        "/api/v1/admin/railway-assistance",
        headers=user_headers,
        json={
            "category": "station_help",
            "title": "Station assistance desk",
            "description": "Help desk at the main concourse.",
            "station_name": "Central",
        },
    )
    assert regular_create.status_code == 403

    user = await db_session.scalar(
        select(User).where(User.email == "rail-admin@example.com")
    )
    assert user is not None
    user.role = "admin"
    await db_session.commit()
    created = await client.post(
        "/api/v1/admin/railway-assistance",
        headers=admin_headers,
        json={
            "category": "station_help",
            "title": "Station assistance desk",
            "description": "Help desk at the main concourse.",
            "station_name": "Central",
        },
    )
    assert created.status_code == 201
    directory = await client.get("/api/v1/railway-assistance", headers=user_headers)
    assert directory.status_code == 200
    assert directory.json()[0]["title"] == "Station assistance desk"


@pytest.mark.asyncio
async def test_push_device_registration_is_authenticated_and_revocable(client):
    _, headers = await register(client, "push-device@example.com")
    initial = await client.get("/api/v1/notifications/devices", headers=headers)
    assert initial.status_code == 200
    assert initial.json() == {"enabled": False}

    token = "ExpoPushToken[012345678901234567890123456789]"
    registered = await client.post(
        "/api/v1/notifications/devices",
        headers=headers,
        json={"expo_push_token": token, "platform": "android"},
    )
    assert registered.status_code == 204
    enabled = await client.get("/api/v1/notifications/devices", headers=headers)
    assert enabled.json() == {"enabled": True}

    revoked = await client.request(
        "DELETE",
        "/api/v1/notifications/devices",
        headers=headers,
        json={"expo_push_token": token, "platform": "android"},
    )
    assert revoked.status_code == 204
    disabled = await client.get("/api/v1/notifications/devices", headers=headers)
    assert disabled.json() == {"enabled": False}
