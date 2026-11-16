from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user
from app.models import RailwayAssistanceRecord, User
from app.schemas import RailwayAssistanceRead

router = APIRouter(prefix="/railway-assistance", tags=["optional railway assistance"])


@router.get("", response_model=list[RailwayAssistanceRead])
async def list_railway_assistance(
    station: str | None = Query(default=None, min_length=1, max_length=160),
    limit: int = Query(default=100, ge=1, le=200),
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[RailwayAssistanceRead]:
    statement = select(RailwayAssistanceRecord).where(
        RailwayAssistanceRecord.is_active.is_(True)
    )
    if station:
        statement = statement.where(
            RailwayAssistanceRecord.station_name.ilike(f"%{station.strip()}%")
        )
    result = await db.execute(
        statement.order_by(
            RailwayAssistanceRecord.station_name,
            RailwayAssistanceRecord.category,
            RailwayAssistanceRecord.title,
        ).limit(limit)
    )
    return list(result.scalars().all())
