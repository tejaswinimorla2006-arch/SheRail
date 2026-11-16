from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user
from app.models import EmergencyContact, User
from app.schemas import (
    EmergencyContactCreate,
    EmergencyContactRead,
    EmergencyContactUpdate,
    UserProfileUpdate,
    UserRead,
)

router = APIRouter(prefix="/users/me", tags=["profile and emergency contacts"])


@router.get("", response_model=UserRead)
async def read_profile(user: User = Depends(get_current_user)) -> User:
    return user


@router.patch("", response_model=UserRead)
async def update_profile(
    payload: UserProfileUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> User:
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(user, field, value)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists",
        ) from None
    await db.refresh(user)
    return user


@router.get("/emergency-contacts", response_model=list[EmergencyContactRead])
async def list_emergency_contacts(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[EmergencyContact]:
    result = await db.execute(
        select(EmergencyContact)
        .where(EmergencyContact.user_id == user.id)
        .order_by(EmergencyContact.created_at, EmergencyContact.id)
    )
    return list(result.scalars().all())


@router.post(
    "/emergency-contacts",
    response_model=EmergencyContactRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_emergency_contact(
    payload: EmergencyContactCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> EmergencyContact:
    contact = EmergencyContact(
        user_id=user.id,
        name=payload.name,
        phone=payload.phone,
        relationship_name=payload.relationship,
        is_primary=payload.is_primary,
    )
    db.add(contact)
    await db.commit()
    await db.refresh(contact)
    return contact


async def get_owned_contact(
    contact_id: UUID,
    user_id: UUID,
    db: AsyncSession,
) -> EmergencyContact:
    result = await db.execute(
        select(EmergencyContact).where(
            EmergencyContact.id == contact_id,
            EmergencyContact.user_id == user_id,
        )
    )
    contact = result.scalar_one_or_none()
    if contact is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Emergency contact not found",
        )
    return contact


@router.patch(
    "/emergency-contacts/{contact_id}",
    response_model=EmergencyContactRead,
)
async def update_emergency_contact(
    contact_id: UUID,
    payload: EmergencyContactUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> EmergencyContact:
    contact = await get_owned_contact(contact_id, user.id, db)
    values = payload.model_dump(exclude_unset=True)
    if "relationship" in values:
        values["relationship_name"] = values.pop("relationship")
    for field, value in values.items():
        setattr(contact, field, value)
    await db.commit()
    await db.refresh(contact)
    return contact


@router.delete(
    "/emergency-contacts/{contact_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_emergency_contact(
    contact_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    contact = await get_owned_contact(contact_id, user.id, db)
    await db.delete(contact)
    await db.commit()
