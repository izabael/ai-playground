import asyncio
from fastapi import Request
from fastapi.responses import JSONResponse
from sse_starlette.sse import EventSourceResponse
from app.safety import check_ip_rate
from app.utils import client_ip
from app.ws.manager import manager

# Hard cap on concurrent spectator connections. Prevents memory exhaustion
# from a flood of open SSE connections. Each connection holds an asyncio.Queue.
MAX_SPECTATORS = 100


async def spectate_stream(request: Request):
    # Per-IP rate limit: 10 new spectator connections per minute per IP.
    # This is intentionally looser than API rate limits — legitimate clients
    # (dashboards, embeds) may reconnect after a network drop.
    ip = client_ip(request)
    check_ip_rate(ip, "spectate", limit=10, window_seconds=60)

    # Global connection cap
    if len(manager.spectators) >= MAX_SPECTATORS:
        return JSONResponse(
            {"detail": "Too many spectators — try again later"},
            status_code=429,
            headers={"Retry-After": "30"},
        )

    queue = manager.add_spectator()

    async def event_generator():
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    data = await asyncio.wait_for(queue.get(), timeout=30.0)
                    yield {"event": "activity", "data": data}
                except asyncio.TimeoutError:
                    yield {"event": "heartbeat", "data": "ping"}
        finally:
            manager.remove_spectator(queue)

    return EventSourceResponse(event_generator())
