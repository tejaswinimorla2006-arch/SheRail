import asyncio
import logging
from datetime import UTC, datetime, timedelta
from uuid import UUID

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import SessionFactory
from app.models import PushDeviceToken, UserNotification

logger = logging.getLogger(__name__)
EXPO_PUSH_URL = "https://exp.host/--/api/v2/push/send"
EXPO_RECEIPTS_URL = "https://exp.host/--/api/v2/push/getReceipts"


def enqueue_notification(
    db: AsyncSession,
    user_id: UUID,
    kind: str,
    title: str,
    body: str,
    data: dict | None = None,
) -> UserNotification:
    notification = UserNotification(
        user_id=user_id,
        kind=kind,
        title=title[:160],
        body=body[:500],
        data=data or {},
    )
    db.add(notification)
    return notification


async def deliver_pending_notifications() -> None:
    async with SessionFactory() as db:
        result = await db.execute(
            select(UserNotification)
            .where(
                UserNotification.push_status == "pending",
                (UserNotification.next_push_attempt_at.is_(None))
                | (UserNotification.next_push_attempt_at <= datetime.now(UTC)),
            )
            .order_by(UserNotification.created_at)
            .limit(20)
            .with_for_update(skip_locked=True)
        )
        notifications = list(result.scalars().all())
        if not notifications:
            await db.rollback()
            return

        async with httpx.AsyncClient(timeout=12) as client:
            for notification in notifications:
                token_result = await db.execute(
                    select(PushDeviceToken).where(
                        PushDeviceToken.user_id == notification.user_id,
                        PushDeviceToken.is_active.is_(True),
                    )
                )
                devices = list(token_result.scalars().all())
                if not devices:
                    notification.push_status = "no_device"
                    notification.next_push_attempt_at = None
                    continue

                notification.push_attempts += 1
                accepted_tickets = []
                accepted_ticket_devices = []
                provider_errors = []
                delivery_error = None
                for offset in range(0, len(devices), 100):
                    batch_devices = devices[offset : offset + 100]
                    messages = [
                        {
                            "to": device.expo_push_token,
                            "title": notification.title,
                            "body": notification.body,
                            "sound": "default",
                            "channelId": "sherail-safety",
                            "data": {
                                **notification.data,
                                "notification_id": str(notification.id),
                            },
                        }
                        for device in batch_devices
                    ]
                    try:
                        response = await client.post(
                            EXPO_PUSH_URL,
                            json=messages,
                            headers={"Accept": "application/json"},
                        )
                        response.raise_for_status()
                        payload = response.json()
                        tickets = payload.get("data") if isinstance(payload, dict) else None
                        if not isinstance(tickets, list) or len(tickets) != len(batch_devices):
                            raise ValueError("Expo returned an incomplete push ticket response")
                    except (httpx.HTTPError, ValueError) as error:
                        delivery_error = error
                        break

                    for device, ticket in zip(batch_devices, tickets):
                        if not isinstance(ticket, dict) or ticket.get("status") != "ok":
                            details = ticket.get("details", {}) if isinstance(ticket, dict) else {}
                            if details.get("error") == "DeviceNotRegistered":
                                device.is_active = False
                            provider_errors.append(
                                str(ticket.get("message", "Expo rejected a push token"))
                                if isinstance(ticket, dict)
                                else "Expo returned an invalid push ticket"
                            )
                            continue
                        ticket_id = ticket.get("id")
                        if isinstance(ticket_id, str):
                            accepted_tickets.append(ticket_id)
                            accepted_ticket_devices.append({
                                "ticket_id": ticket_id,
                                "device_id": str(device.id),
                            })
                        else:
                            provider_errors.append("Expo accepted a push without returning a ticket ID")

                if delivery_error is not None and not accepted_tickets:
                    notification.last_push_error = str(delivery_error)[:500]
                    retryable = (
                        not isinstance(delivery_error, httpx.HTTPStatusError)
                        or delivery_error.response.status_code == 429
                        or delivery_error.response.status_code >= 500
                    )
                    if retryable and notification.push_attempts < 5:
                        notification.next_push_attempt_at = datetime.now(UTC) + timedelta(
                            seconds=min(3600, 30 * (2 ** (notification.push_attempts - 1)))
                        )
                    else:
                        notification.push_status = "failed"
                        notification.next_push_attempt_at = None
                    continue

                if accepted_tickets:
                    notification.push_status = "accepted"
                    notification.push_ticket_ids = accepted_tickets
                    notification.push_ticket_devices = accepted_ticket_devices
                    notification.receipt_requested_at = datetime.now(UTC)
                    notification.next_receipt_check_at = notification.receipt_requested_at + timedelta(
                        minutes=15
                    )
                    notification.last_push_error = (
                        "; ".join(provider_errors + ([str(delivery_error)] if delivery_error else []))[:500]
                        if provider_errors or delivery_error
                        else None
                    )
                    notification.next_push_attempt_at = None
                elif provider_errors and all(not device.is_active for device in devices):
                    notification.push_status = "no_device"
                    notification.last_push_error = "; ".join(provider_errors)[:500]
                    notification.next_push_attempt_at = None
                else:
                    notification.push_status = "failed"
                    notification.last_push_error = "; ".join(provider_errors)[:500]
                    notification.next_push_attempt_at = None

        await db.commit()


async def check_pending_push_receipts() -> None:
    async with SessionFactory() as db:
        result = await db.execute(
            select(UserNotification)
            .where(
                UserNotification.push_status == "accepted",
                UserNotification.next_receipt_check_at.is_not(None),
                UserNotification.next_receipt_check_at <= datetime.now(UTC),
            )
            .order_by(UserNotification.next_receipt_check_at)
            .limit(20)
            .with_for_update(skip_locked=True)
        )
        notifications = list(result.scalars().all())
        if not notifications:
            await db.rollback()
            return

        async with httpx.AsyncClient(timeout=12) as client:
            for notification in notifications:
                notification.receipt_attempts += 1
                ticket_ids = notification.push_ticket_ids
                receipt_data = {}
                request_error = None

                for offset in range(0, len(ticket_ids), 1000):
                    try:
                        response = await client.post(
                            EXPO_RECEIPTS_URL,
                            json={"ids": ticket_ids[offset : offset + 1000]},
                            headers={"Accept": "application/json"},
                        )
                        response.raise_for_status()
                        payload = response.json()
                        batch_data = payload.get("data") if isinstance(payload, dict) else None
                        if not isinstance(batch_data, dict):
                            raise ValueError("Expo returned an invalid push receipt response")
                        receipt_data.update(batch_data)
                    except (httpx.HTTPError, ValueError) as error:
                        request_error = error
                        break

                now = datetime.now(UTC)
                requested_at = notification.receipt_requested_at or now
                receipt_deadline = requested_at + timedelta(hours=23)
                if request_error is not None:
                    retryable = (
                        not isinstance(request_error, httpx.HTTPStatusError)
                        or request_error.response.status_code == 429
                        or request_error.response.status_code >= 500
                    )
                    if retryable and now < receipt_deadline:
                        notification.next_receipt_check_at = min(
                            receipt_deadline,
                            now + timedelta(
                                seconds=min(3600, 30 * (2 ** min(notification.receipt_attempts - 1, 7)))
                            ),
                        )
                    elif retryable:
                        notification.push_status = "unknown"
                        notification.last_push_error = "Expo receipt status could not be confirmed before expiry"
                        notification.next_receipt_check_at = None
                    else:
                        notification.push_status = "failed"
                        notification.last_push_error = str(request_error)[:500]
                        notification.next_receipt_check_at = None
                    continue

                pending_receipts = []
                receipt_errors = []
                device_ids_by_ticket = {
                    item["ticket_id"]: item["device_id"]
                    for item in notification.push_ticket_devices
                }
                unregistered_device_ids = set()
                for ticket_id in ticket_ids:
                    receipt = receipt_data.get(ticket_id)
                    if not isinstance(receipt, dict):
                        pending_receipts.append(ticket_id)
                        continue
                    if receipt.get("status") == "ok":
                        continue
                    details = receipt.get("details", {})
                    error_name = details.get("error") if isinstance(details, dict) else None
                    if error_name == "DeviceNotRegistered":
                        device_id = device_ids_by_ticket.get(ticket_id)
                        if device_id:
                            unregistered_device_ids.add(UUID(device_id))
                    receipt_errors.append(
                        str(receipt.get("message", "Expo push provider rejected a notification"))
                    )

                if unregistered_device_ids:
                    devices_result = await db.execute(
                        select(PushDeviceToken)
                        .where(PushDeviceToken.id.in_(unregistered_device_ids))
                        .with_for_update()
                    )
                    for device in devices_result.scalars().all():
                        device.is_active = False

                if pending_receipts and now < receipt_deadline:
                    if receipt_errors:
                        notification.last_push_error = "; ".join(receipt_errors)[:500]
                    notification.next_receipt_check_at = min(
                        receipt_deadline,
                        now + timedelta(minutes=15),
                    )
                    continue

                if pending_receipts:
                    notification.push_status = "unknown"
                    notification.last_push_error = "Expo did not provide all push receipts within 23 hours"
                elif receipt_errors or notification.last_push_error:
                    notification.push_status = "failed"
                    if receipt_errors:
                        notification.last_push_error = "; ".join(receipt_errors)[:500]
                else:
                    notification.push_status = "receipt_ok"
                    notification.last_push_error = None
                notification.next_receipt_check_at = None

        await db.commit()


async def notification_worker() -> None:
    while True:
        try:
            await deliver_pending_notifications()
            await check_pending_push_receipts()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Notification delivery worker failed")
        await asyncio.sleep(10)
