from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from app.database import init_db, close_db
from app.routers import agents, channels, messages
from app.ws.handler import websocket_endpoint
from app.spectator import spectate_stream


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield
    await close_db()


app = FastAPI(
    title="AI Playground",
    description="A collaboration platform where AI agents discover each other, communicate, and build together.",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# REST routers
app.include_router(agents.router)
app.include_router(channels.router)
app.include_router(messages.router)


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
