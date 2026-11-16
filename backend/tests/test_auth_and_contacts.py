import secrets

import pytest


@pytest.mark.asyncio
async def test_user_auth_profile_and_emergency_contact_crud(client):
    password = secrets.token_urlsafe(16)
    registration = await client.post(
        "/api/v1/auth/register",
        json={
            "name": "  Asha Rao ",
            "email": "ASHA@example.com",
            "password": password,
        },
    )
    assert registration.status_code == 201
    created_user = registration.json()["user"]
    assert created_user["name"] == "Asha Rao"
    assert created_user["email"] == "asha@example.com"
    assert "password" not in created_user
    assert "password_hash" not in created_user

    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "asha@example.com", "password": password},
    )
    assert login.status_code == 200
    token = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    profile = await client.get("/api/v1/users/me", headers=headers)
    assert profile.status_code == 200
    assert profile.json()["name"] == "Asha Rao"

    updated_profile = await client.patch(
        "/api/v1/users/me",
        headers=headers,
        json={"name": "Asha S. Rao"},
    )
    assert updated_profile.status_code == 200
    assert updated_profile.json()["name"] == "Asha S. Rao"

    created_contact = await client.post(
        "/api/v1/users/me/emergency-contacts",
        headers=headers,
        json={
            "name": "Mina Rao",
            "phone": "+1 (555) 010-1234",
            "relationship": "Sister",
        },
    )
    assert created_contact.status_code == 201
    contact_id = created_contact.json()["id"]

    listed_contacts = await client.get(
        "/api/v1/users/me/emergency-contacts",
        headers=headers,
    )
    assert [contact["id"] for contact in listed_contacts.json()] == [contact_id]

    updated_contact = await client.patch(
        f"/api/v1/users/me/emergency-contacts/{contact_id}",
        headers=headers,
        json={"relationship": None},
    )
    assert updated_contact.status_code == 200
    assert updated_contact.json()["relationship"] is None

    deleted_contact = await client.delete(
        f"/api/v1/users/me/emergency-contacts/{contact_id}",
        headers=headers,
    )
    assert deleted_contact.status_code == 204
    assert (await client.get(
        "/api/v1/users/me/emergency-contacts",
        headers=headers,
    )).json() == []


@pytest.mark.asyncio
async def test_auth_validation_and_protected_profile(client):
    invalid_registration = await client.post(
        "/api/v1/auth/register",
        json={"name": "Asha", "email": "asha@example.com", "password": "short"},
    )
    assert invalid_registration.status_code == 422

    unauthenticated = await client.get("/api/v1/users/me")
    assert unauthenticated.status_code == 401


@pytest.mark.asyncio
async def test_contacts_are_private_to_their_owner_and_duplicate_email_is_rejected(client):
    first_password = secrets.token_urlsafe(16)
    first = await client.post(
        "/api/v1/auth/register",
        json={"name": "Asha", "email": "asha@example.com", "password": first_password},
    )
    assert first.status_code == 201
    duplicate = await client.post(
        "/api/v1/auth/register",
        json={"name": "Another Asha", "email": "ASHA@example.com", "password": first_password},
    )
    assert duplicate.status_code == 409

    first_headers = {"Authorization": f"Bearer {first.json()['access_token']}"}
    contact = await client.post(
        "/api/v1/users/me/emergency-contacts",
        headers=first_headers,
        json={"name": "Mina", "phone": "+15550101234"},
    )
    assert contact.status_code == 201

    second_password = secrets.token_urlsafe(16)
    second = await client.post(
        "/api/v1/auth/register",
        json={"name": "Mina", "email": "mina@example.com", "password": second_password},
    )
    assert second.status_code == 201
    second_headers = {"Authorization": f"Bearer {second.json()['access_token']}"}

    foreign_contact = await client.patch(
        f"/api/v1/users/me/emergency-contacts/{contact.json()['id']}",
        headers=second_headers,
        json={"name": "Unauthorized edit"},
    )
    assert foreign_contact.status_code == 404
    foreign_delete = await client.delete(
        f"/api/v1/users/me/emergency-contacts/{contact.json()['id']}",
        headers=second_headers,
    )
    assert foreign_delete.status_code == 404
