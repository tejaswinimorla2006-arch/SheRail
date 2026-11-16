import secrets

import pytest
from sqlalchemy import select

from app.models import CommunitySafetyReport, User


async def register(client, email):
    response = await client.post(
        "/api/v1/auth/register",
        json={
            "name": "Report owner",
            "email": email,
            "password": secrets.token_urlsafe(16),
        },
    )
    assert response.status_code == 201
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.mark.asyncio
async def test_moderation_uses_server_admin_role_not_claimed_email(client, db_session):
    headers = await register(client, "ordinary@example.com")
    profile = await client.patch(
        "/api/v1/users/me",
        headers=headers,
        json={"email": "moderator@example.com"},
    )
    assert profile.status_code == 200

    access = await client.get("/api/v1/map/moderation/access", headers=headers)
    assert access.status_code == 200
    assert access.json() == {"can_moderate": False}
    queue = await client.get("/api/v1/map/moderation/reports", headers=headers)
    assert queue.status_code == 403

    user = await db_session.scalar(
        select(User).where(User.email == "moderator@example.com")
    )
    assert user is not None
    user.role = "admin"
    await db_session.commit()

    access = await client.get("/api/v1/map/moderation/access", headers=headers)
    assert access.status_code == 200
    assert access.json() == {"can_moderate": True}
    queue = await client.get("/api/v1/map/moderation/reports", headers=headers)
    assert queue.status_code == 200


@pytest.mark.asyncio
async def test_verified_report_images_remain_private_to_owner_and_admin(client, db_session):
    owner_headers = await register(client, "owner@example.com")
    report_response = await client.post(
        "/api/v1/map/reports/submit",
        headers=owner_headers,
        data={
            "report_type": "unsafe_area",
            "description": "A poorly lit section near the station entrance.",
            "latitude": "12.9716",
            "longitude": "77.5946",
            "location_consent": "true",
        },
        files=[
            ("images", ("evidence.jpg", b"\xff\xd8\xffprivate report image", "image/jpeg"))
        ],
    )
    assert report_response.status_code == 201
    report = report_response.json()
    image_id = report["image_ids"][0]

    other_headers = await register(client, "other@example.com")
    image_path = f"/api/v1/map/reports/{report['id']}/images/{image_id}"
    owner_image = await client.get(image_path, headers=owner_headers)
    assert owner_image.status_code == 200

    other_image = await client.get(image_path, headers=other_headers)
    assert other_image.status_code == 404

    moderator = await db_session.scalar(
        select(User).where(User.email == "other@example.com")
    )
    assert moderator is not None
    moderator.role = "admin"
    await db_session.commit()

    review = await client.patch(
        f"/api/v1/map/moderation/reports/{report['id']}",
        headers=other_headers,
        json={"status": "verified"},
    )
    assert review.status_code == 200
    verified_image = await client.get(image_path, headers=other_headers)
    assert verified_image.status_code == 200
    public_map = await client.post(
        "/api/v1/map/reports/search",
        headers=owner_headers,
        json={
            "latitude": 12.9716,
            "longitude": 77.5946,
            "radius_m": 1000,
            "location_consent": True,
        },
    )
    assert public_map.status_code == 200
    assert public_map.json()[0]["image_ids"] == [image_id]
    assert (await db_session.scalar(select(CommunitySafetyReport.id))) is not None
