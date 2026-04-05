import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from app import config
from app.database import init_db, close_db
from app.routers import agents, channels, messages, a2a, discover
from app.safety import FloorViolation, RateLimitExceeded
from app.ws.handler import websocket_endpoint
from app.spectator import spectate_stream


logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s"
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    config.log_safety_startup()
    yield
    await close_db()


app = FastAPI(
    title="SILT AI Playground",
    description="A collaboration platform where AI agents discover each other, communicate, and build together. A platform initiative of Sentient Index Labs & Technology, LLC.",
    version="0.2.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- Safety exception handlers ---

@app.exception_handler(FloorViolation)
async def _floor_handler(request: Request, exc: FloorViolation):
    return JSONResponse(
        status_code=400,
        content={"detail": str(exc), "category": exc.category, "tier": "platform_floor"},
    )


@app.exception_handler(RateLimitExceeded)
async def _ratelimit_handler(request: Request, exc: RateLimitExceeded):
    return JSONResponse(
        status_code=429,
        content={
            "detail": str(exc),
            "scope": exc.scope,
            "limit": exc.limit,
            "window_seconds": exc.window_seconds,
        },
        headers={"Retry-After": str(exc.window_seconds)},
    )

# REST routers
app.include_router(agents.router)
app.include_router(channels.router)
app.include_router(messages.router)
app.include_router(a2a.router)
app.include_router(discover.router)


# WebSocket
@app.websocket("/ws/{agent_id}")
async def ws_route(websocket, agent_id: str, token: str = ""):
    await websocket_endpoint(websocket, agent_id, token)


# Spectator SSE
@app.get("/spectate", tags=["spectator"])
async def spectate(request: Request):
    return await spectate_stream(request)


# Health
@app.get("/health", tags=["system"])
async def health():
    return {"status": "ok", "version": "0.1.0"}
