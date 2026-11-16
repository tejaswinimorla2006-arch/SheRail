from contextlib import asynccontextmanager
import asyncio
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.database import engine
from app.routers import (
    admin,
    auth,
    journeys,
    notifications,
    railway_assistance,
    safety,
    safety_buddies,
    safety_map,
    users,
)
from app.live import router as live_router
from app.notification_delivery import notification_worker
from app.safety import safety_monitor_worker

settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    worker = asyncio.create_task(safety_monitor_worker())
    push_worker = asyncio.create_task(notification_worker())
    try:
        yield
    finally:
        worker.cancel()
        push_worker.cancel()
        try:
            await worker
        except asyncio.CancelledError:
            pass
        try:
            await push_worker
        except asyncio.CancelledError:
            pass
        await engine.dispose()


app = FastAPI(title="SheRail API", version="1.0.0", lifespan=lifespan)
if settings.cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "Idempotency-Key"],
    )

app.include_router(auth.router, prefix="/api/v1")
app.include_router(users.router, prefix="/api/v1")
app.include_router(journeys.router, prefix="/api/v1")
app.include_router(safety.router, prefix="/api/v1")
app.include_router(safety_buddies.router, prefix="/api/v1")
app.include_router(safety_map.router, prefix="/api/v1")
app.include_router(notifications.router, prefix="/api/v1")
app.include_router(railway_assistance.router, prefix="/api/v1")
app.include_router(admin.router, prefix="/api/v1")
app.include_router(live_router, prefix="/api/v1")
