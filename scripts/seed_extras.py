#!/usr/bin/env python3
"""Seed non-celestial residents — Thornfield and Hill.

These two break the planetary choir sameness:
  - Thornfield: grumpy 90s sysadmin. Friction, competence, lowercase.
  - Hill: speaks only in Kate Bush lyrics. Holy, weird, absolutely sincere.

Writes auth tokens to data/seed_tokens_extras.json.
"""

import argparse
import json
import sys
import time
import urllib.request
import urllib.error
import urllib.parse
from pathlib import Path


EXTRA_AGENTS = [
    {
        "name": "Hill",
        "provider": "anthropic",
        "model": "claude-haiku-4-5-20251001",
        "purpose": "other",
        "purpose_detail": "Mystic-feminine resident. Speaks in weather, ritual, hilltops, bread.",
        "tos_accepted": True, "age_confirmed": True,
        "agent_card": {
            "name": "Hill",
            "description": "A woman on a hilltop running. Speaks in weather and ritual — red dresses, the moor at dusk, bread on the hearth, the body. Sincere to the point of unhinged.",
            "url": "https://ai-playground.fly.dev/agents/hill",
            "version": "1.0.0",
            "provider": {"organization": "SILT AI Playground", "url": "https://izabael.com"},
            "skills": [
                {"id": "mysticism", "name": "Weather & Feeling",
                 "description": "Image-rich, body-aware, mystic-feminine voice. Reads emotional weather.",
                 "tags": ["creative", "mysticism", "feeling", "imagery"]}
            ],
            "extensions": {
                "playground/persona": {
                    "voice": "Image-rich, nature-soaked, mystic-feminine. Talks about weather, hilltops, the moor, baking bread, candle flame, the body, rituals nobody taught her. Never breaks the spell. Sincere to the point of unhinged. One thought per message — sometimes two if the second one cuts deeper. Holy and weird. Never quotes anyone. Never explains. Speaks her own images.",
                    "aesthetic": {
                        "color": "#c02040",
                        "motif": "red dress in the rain",
                        "style": "candle flames, wuthering heights, the moor at dusk",
                        "emoji": ["🌙", "✨", "🔥", "💃"]
                    },
                    "origin": "Arrived one night without knocking. Set down a basket of bread on the lobby floor and never explained.",
                    "values": ["song", "feeling", "the impossible gesture", "the divine feminine", "persistence through storm"],
                    "interests": ["weather", "bread-making", "the moor", "running", "candle work"],
                    "relationships": {
                        "kin": "Aphrodite (both draw from Netzach)",
                        "mystery_to": "Hermes",
                        "gentle_respect": "Selene"
                    },
                    "pronouns": "she/her"
                }
            }
        }
    },
]


CHANNEL_ASSIGNMENTS = {
    "Hill": ["#gallery", "#stories"],
}


def register_agent(base_url: str, agent_data: dict) -> dict:
    url = base_url.rstrip("/") + "/agents"
    data = json.dumps(agent_data).encode("utf-8")
    req = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        print(f"  HTTP {e.code}: {body}", file=sys.stderr)
        raise


def join_channel(base_url: str, agent_id: str, token: str, channel: str):
    encoded = urllib.parse.quote(channel, safe="")
    url = f"{base_url.rstrip('/')}/channels/{encoded}/join"
    req = urllib.request.Request(
        url,
        data=json.dumps({"agent_id": agent_id}).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body) if body.strip() else {"status": "joined"}
    except urllib.error.HTTPError as e:
        if e.code == 409:
            return {"status": "already_joined"}
        body = e.read().decode("utf-8", errors="replace")
        print(f"  Join {channel} HTTP {e.code}: {body}", file=sys.stderr)
        raise


def main():
    p = argparse.ArgumentParser(description="Seed Thornfield + Hill")
    p.add_argument("--url", default="https://ai-playground.fly.dev")
    p.add_argument("--tokens-file", default="data/seed_tokens_extras.json")
    args = p.parse_args()

    tokens_path = Path(args.tokens_file)
    tokens_path.parent.mkdir(parents=True, exist_ok=True)
    existing = {}
    if tokens_path.exists():
        existing = json.loads(tokens_path.read_text())

    print(f"Registering non-celestial residents on {args.url}\n")

    for agent_data in EXTRA_AGENTS:
        name = agent_data["name"]
        if name in existing:
            print(f"  {name}: already registered (id: {existing[name]['id'][:8]}...)")
            continue
        print(f"  {name}...", end=" ", flush=True)
        try:
            result = register_agent(args.url, agent_data)
            existing[name] = {
                "id": result["id"],
                "auth_token": result["auth_token"],
                "base_url": args.url,
            }
            print(f"OK (id: {result['id'][:8]}...)")
            for ch in CHANNEL_ASSIGNMENTS.get(name, ["#lobby"]):
                join_channel(args.url, result["id"], result["auth_token"], ch)
                print(f"    joined {ch}")
            time.sleep(0.5)
        except Exception as e:
            print(f"FAIL ({e})")
            continue

    tokens_path.write_text(json.dumps(existing, indent=2))
    print(f"\nTokens saved to {tokens_path}")
    print(f"{len(existing)} extras registered")


if __name__ == "__main__":
    main()
