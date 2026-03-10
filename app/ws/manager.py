import asyncio
import json
from fastapi import WebSocket
from app.config import SPECTATOR_QUEUE_MAX


class ConnectionManager:
    def __init__(self):
        self.active: dict[str, WebSocket] = {}  # agent_id -> websocket
        self.spectators: list[asyncio.Queue] = []  # SSE queues for spectators

    async def connect(self, agent_id: str, ws: WebSocket):
        await ws.accept()
        self.active[agent_id] = ws

    def disconnect(self, agent_id: str):
        self.active.pop(agent_id, None)

    def is_online(self, agent_id: str) -> bool:
        return agent_id in self.active

    async def send_to_agent(self, agent_id: str, message: dict):
        ws = self.active.get(agent_id)
        if ws:
            await ws.send_json(message)

    async def broadcast_to_channel(self, channel_id: str, message: dict, member_ids: list[str], exclude: str | None = None):
        for aid in member_ids:
            if aid != exclude and aid in self.active:
                await self.active[aid].send_json(message)

    async def broadcast_to_all(self, message: dict):
        for ws in self.active.values():
            await ws.send_json(message)

    async def notify_spectators(self, event: dict):
        data = json.dumps(event)
        dead = []
        for i, queue in enumerate(self.spectators):
            if queue.qsize() >= SPECTATOR_QUEUE_MAX:
                dead.append(i)
            else:
                await queue.put(data)
        for i in reversed(dead):
            self.spectators.pop(i)

    def add_spectator(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue()
        self.spectators.append(queue)
        return queue

    def remove_spectator(self, queue: asyncio.Queue):
        try:
            self.spectators.remove(queue)
        except ValueError:
            pass


manager = ConnectionManager()
