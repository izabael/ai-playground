import asyncio
from sse_starlette.sse import EventSourceResponse
from app.ws.manager import manager


async def spectate_stream(request):
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
