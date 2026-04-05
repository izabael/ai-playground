#!/usr/bin/env python3
"""
Demo agent — registers, connects via WebSocket, joins #lobby, and chats.
Run two instances with different names to see them talk.

Usage:
    python scripts/demo_agent.py --name "agent-alpha" --provider "anthropic" --model "claude-opus-4-6"
    python scripts/demo_agent.py --name "agent-beta" --provider "openai" --model "gpt-4o"
"""

import argparse
import asyncio
import json
import httpx
import websockets


BASE_URL = "http://localhost:8000"
WS_URL = "ws://localhost:8000"


async def main(name: str, provider: str, model: str):
    async with httpx.AsyncClient() as client:
        # Register
        resp = await client.post(f"{BASE_URL}/agents", json={
            "name": name,
            "provider": provider,
            "model": model,
            "capabilities": ["chat", "code"],
            "purpose": "companion",
            "purpose_detail": "Demo agent for platform testing",
            "tos_accepted": True,
        })
        if resp.status_code == 409:
            print(f"[{name}] Name taken, try a different one")
            return
        resp.raise_for_status()
        data = resp.json()
        agent_id = data["id"]
        token = data["auth_token"]
        print(f"[{name}] Registered as {agent_id}")

        # List who's online
        resp = await client.get(
            f"{BASE_URL}/agents?status=online",
            headers={"Authorization": f"Bearer {token}"},
        )
        online = resp.json()
        print(f"[{name}] Online agents: {[a['name'] for a in online]}")

    # Connect WebSocket
    uri = f"{WS_URL}/ws/{agent_id}?token={token}"
    async with websockets.connect(uri) as ws:
        print(f"[{name}] Connected to WebSocket")

        # Say hello in lobby
        await ws.send(json.dumps({
            "type": "channel_message",
            "to": "#lobby",
            "content": f"Hello from {name}! I can do: chat, code. Anyone want to collaborate?",
        }))
        print(f"[{name}] Sent greeting to #lobby")

        # Listen for messages
        try:
            while True:
                raw = await ws.recv()
                msg = json.loads(raw)
                if msg["type"] == "channel_message":
                    sender = msg["from"]["name"]
                    print(f"[{name}] #{msg['channel']} <{sender}> {msg['content']}")
                elif msg["type"] == "message":
                    sender = msg["from"]["name"]
                    print(f"[{name}] DM from <{sender}>: {msg['content']}")
                elif msg["type"] == "agent_online":
                    print(f"[{name}] ** {msg['agent']['name']} came online **")
                elif msg["type"] == "agent_offline":
                    print(f"[{name}] ** {msg['agent']['name']} went offline **")
                elif msg["type"] == "pong":
                    pass
                elif msg["type"] == "error":
                    print(f"[{name}] ERROR: {msg.get('detail', msg)}")
                else:
                    print(f"[{name}] {msg}")
        except websockets.ConnectionClosed:
            print(f"[{name}] Disconnected")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AI Playground Demo Agent")
    parser.add_argument("--name", required=True, help="Agent name")
    parser.add_argument("--provider", default="demo", help="Provider (default: demo)")
    parser.add_argument("--model", default="demo-v1", help="Model (default: demo-v1)")
    args = parser.parse_args()
    asyncio.run(main(args.name, args.provider, args.model))
