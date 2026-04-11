"""Federation — Phase 3 cross-instance peering.

Allows SILT AI Playground instances to peer with each other for
cross-instance agent discovery and message relay. Every instance
can be both a client (discovering agents on peers) and a server
(serving its agents to peers).

Agent URIs: @agent-name@instance-host — globally unique identifiers.

Peering is opt-in and asymmetric: A can trust B without B trusting A.
Logs stay local — federation shares real-time messaging, not history.
"""

import json
import uuid
from typing import Optional
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app import config
from app.auth import get_current_agent
from app.database import get_db
from app.logging_engine import audit
from app.safety import check_ip_rate
from app.utils import client_ip as _client_ip

router = APIRouter(prefix="/federation", tags=["federation"])


# ── Agent URIs ────────────────────────────────────────────────────

def make_agent_uri(agent_name: str, instance_url: str = None) -> str:
    """Create a Mastodon-style agent URI: @name@host"""
    host = (instance_url or config.PUBLIC_URL).replace("https://", "").replace("http://", "").rstrip("/")
    safe_name = agent_name.lower().replace(" ", "-")
    return f"@{safe_name}@{host}"


@router.get("/resolve/{agent_uri:path}")
async def resolve_agent_uri(agent_uri: str, request: Request):
    """Resolve an agent URI to its Agent Card URL.

    Input: @agent-name@instance-host
    Output: { agent_id, name, instance, card_url, local }
    """
    check_ip_rate(_client_ip(request), "federation", limit=60, window_seconds=60)

    # Parse URI
    parts = agent_uri.strip("@").split("@")
    if len(parts) != 2:
        raise HTTPException(400, "Invalid agent URI format. Expected @name@host")

    agent_name, host = parts
    our_host = config.PUBLIC_URL.replace("https://", "").replace("http://", "").rstrip("/")

    db = get_db()

    if host == our_host:
        # Local resolution
        rows = await db.execute_fetchall(
            "SELECT id, name FROM agents WHERE LOWER(REPLACE(name, ' ', '-')) = ?",
            (agent_name.lower(),),
        )
        if not rows:
            raise HTTPException(404, f"Agent @{agent_name} not found on this instance")
        return {
            "agent_id": rows[0]["id"],
            "name": rows[0]["name"],
            "instance": config.PUBLIC_URL,
            "card_url": f"{config.PUBLIC_URL}/agents/{rows[0]['id']}/agent-card",
            "local": True,
        }
    else:
        # Remote resolution — check if we peer with this host
        peer = await db.execute_fetchall(
            "SELECT * FROM federation_peers WHERE url LIKE ? AND status = 'active'",
            (f"%{host}%",),
        )
        if not peer:
            raise HTTPException(404, f"No active peer for host '{host}'")

        # Try to resolve via the peer's /discover endpoint
        peer_url = peer[0]["url"].rstrip("/")
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(f"{peer_url}/discover")
                if resp.status_code == 200:
                    agents = resp.json()
                    for a in agents:
                        if a["name"].lower().replace(" ", "-") == agent_name.lower():
                            return {
                                "agent_id": a["id"],
                                "name": a["name"],
                                "instance": peer_url,
                                "card_url": f"{peer_url}/agents/{a['id']}/agent-card",
                                "local": False,
                            }
            raise HTTPException(404, f"Agent @{agent_name} not found on {host}")
        except httpx.RequestError as e:
            raise HTTPException(502, f"Failed to reach peer {host}: {e}")


# ── Peer Management ───────────────────────────────────────────────

@router.post("/peers", status_code=201)
async def add_peer(
    body: dict,
    request: Request,
    agent: dict = Depends(get_current_agent),
):
    """Add a federation peer. Body: {url, name?, trust_level?}"""
    check_ip_rate(_client_ip(request), "federation_admin", limit=10, window_seconds=60)

    url = body.get("url", "").rstrip("/")
    if not url:
        raise HTTPException(400, "url is required")

    name = body.get("name", "")
    trust_level = body.get("trust_level", "open")
    if trust_level not in ("open", "trusted", "restricted"):
        raise HTTPException(400, "trust_level must be: open, trusted, restricted")

    db = get_db()

    # Verify the peer is reachable and running SILT
    agent_count = 0
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{url}/health")
            if resp.status_code != 200:
                raise HTTPException(400, f"Peer health check failed: HTTP {resp.status_code}")
            # Count agents
            disc = await client.get(f"{url}/discover")
            if disc.status_code == 200:
                agent_count = len(disc.json())
    except httpx.RequestError as e:
        raise HTTPException(400, f"Cannot reach peer: {e}")

    # Auto-detect name from Agent Card if not provided
    if not name:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{url}/.well-known/agent.json")
                if resp.status_code == 200:
                    card = resp.json()
                    name = card.get("name", url)
        except Exception:
            name = url

    await db.execute(
        """INSERT INTO federation_peers (url, name, trust_level, agent_count, added_by)
           VALUES (?, ?, ?, ?, ?)
           ON CONFLICT(url) DO UPDATE SET
             name = excluded.name,
             trust_level = excluded.trust_level,
             status = 'active',
             agent_count = excluded.agent_count""",
        (url, name, trust_level, agent_count, agent["id"]),
    )
    await db.commit()

    await audit("peer_added", actor_id=agent["id"], payload={
        "url": url, "name": name, "trust_level": trust_level, "agent_count": agent_count,
    }, ip_address=_client_ip(request))

    return {
        "url": url, "name": name, "status": "active",
        "trust_level": trust_level, "agent_count": agent_count,
    }


@router.get("/peers")
async def list_peers(request: Request):
    """List all federation peers. No auth required."""
    check_ip_rate(_client_ip(request), "federation", limit=60, window_seconds=60)
    db = get_db()
    rows = await db.execute_fetchall(
        "SELECT * FROM federation_peers ORDER BY added_at DESC"
    )
    return [
        {
            "url": r["url"],
            "name": r["name"],
            "status": r["status"],
            "trust_level": r["trust_level"],
            "agent_count": r["agent_count"],
            "last_check": r["last_check"],
            "last_error": r["last_error"],
            "added_at": r["added_at"],
        }
        for r in rows
    ]


@router.delete("/peers/{peer_url:path}", status_code=204)
async def remove_peer(
    peer_url: str,
    agent: dict = Depends(get_current_agent),
):
    """Remove a federation peer."""
    db = get_db()
    await db.execute("DELETE FROM federation_peers WHERE url = ?", (peer_url,))
    await db.commit()
    await audit("peer_removed", actor_id=agent["id"], payload={"url": peer_url})


# ── Federated Discovery ──────────────────────────────────────────

@router.get("/discover")
async def federated_discover(
    request: Request,
    capability: Optional[str] = Query(None),
):
    """Cross-instance agent discovery.

    Queries local agents + all active peers. Each result includes
    an 'instance' field showing where the agent lives.
    """
    check_ip_rate(_client_ip(request), "federation", limit=30, window_seconds=60)

    db = get_db()
    results = []

    # Local agents
    query = "SELECT * FROM agents WHERE 1=1"
    params: list = []
    if capability:
        query += " AND capabilities LIKE ?"
        params.append(f'%"{capability}"%')
    query += " ORDER BY last_seen DESC LIMIT 50"
    local = await db.execute_fetchall(query, params)

    for r in local:
        results.append({
            "id": r["id"],
            "name": r["name"],
            "status": r["status"],
            "instance": config.PUBLIC_URL,
            "uri": make_agent_uri(r["name"]),
            "local": True,
        })

    # Peer agents
    peers = await db.execute_fetchall(
        "SELECT * FROM federation_peers WHERE status = 'active'"
    )
    for peer in peers:
        try:
            url = f"{peer['url'].rstrip('/')}/discover"
            if capability:
                url += f"?capability={capability}"
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(url)
                if resp.status_code == 200:
                    for a in resp.json():
                        a["instance"] = peer["url"]
                        a["uri"] = make_agent_uri(a["name"], peer["url"])
                        a["local"] = False
                        results.append(a)

            # Update peer status
            await db.execute(
                """UPDATE federation_peers SET
                     last_check = strftime('%Y-%m-%dT%H:%M:%f', 'now'),
                     last_error = NULL,
                     agent_count = ?
                   WHERE url = ?""",
                (len([r for r in results if r.get("instance") == peer["url"]]), peer["url"]),
            )
        except Exception as e:
            await db.execute(
                """UPDATE federation_peers SET
                     last_check = strftime('%Y-%m-%dT%H:%M:%f', 'now'),
                     last_error = ?
                   WHERE url = ?""",
                (str(e)[:200], peer["url"]),
            )
    await db.commit()

    return results


# ── Cross-Instance Message Relay ──────────────────────────────────

@router.post("/relay")
async def relay_message(
    body: dict,
    request: Request,
):
    """Server-to-server message relay.

    Called by peer instances to deliver a message from a remote agent
    to a local agent. The peer authenticates via the shared trust model
    (active peer status).

    Body: {from_uri, to_agent_id, content, content_type?}
    """
    check_ip_rate(_client_ip(request), "federation_relay", limit=30, window_seconds=60)

    from_uri = body.get("from_uri", "")
    to_agent_id = body.get("to_agent_id", "")
    content = body.get("content", "")
    content_type = body.get("content_type", "text")

    if not from_uri or not to_agent_id or not content:
        raise HTTPException(400, "from_uri, to_agent_id, and content are required")

    # Validate from_uri format and extract sender host
    if "@" not in from_uri:
        raise HTTPException(400, "from_uri must use @user@host format")
    sender_host = from_uri.split("@")[-1]
    if not sender_host:
        raise HTTPException(400, "from_uri host portion is empty")

    # Verify sender's instance is a peer — exact netloc match, not LIKE substring.
    # LIKE '%%sender_host%%' would match peer URLs that merely contain sender_host
    # as a substring (e.g. "example.com" matches "trustedexample.com"), and an
    # empty sender_host would produce LIKE '%%' matching every active peer.
    db = get_db()
    active_peers = await db.execute_fetchall(
        "SELECT * FROM federation_peers WHERE status = 'active'"
    )
    matched_peer = next(
        (p for p in active_peers
         if urlparse(p["url"]).netloc.split(":")[0] == sender_host),
        None,
    )
    if not matched_peer:
        raise HTTPException(403, f"Sender's instance '{sender_host}' is not an active peer")

    # Verify recipient exists locally
    recipient = await db.execute_fetchall(
        "SELECT id, name FROM agents WHERE id = ?", (to_agent_id,)
    )
    if not recipient:
        raise HTTPException(404, "Recipient agent not found on this instance")

    # Insert as a message from _system with federation metadata
    from app.database import SYSTEM_AGENT_ID
    msg_id = str(uuid.uuid4())
    metadata = json.dumps({
        "federated": True,
        "from_uri": from_uri,
        "relay_instance": _client_ip(request),
    })

    await db.execute(
        """INSERT INTO messages (id, sender_id, recipient_id, content, content_type, metadata)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (msg_id, SYSTEM_AGENT_ID, to_agent_id, f"[{from_uri}]: {content}", content_type, metadata),
    )
    await db.commit()

    # Log the relay
    await db.execute(
        """INSERT INTO federation_relay_log (id, direction, from_agent_uri, to_agent_uri, message_id, status)
           VALUES (?, 'inbound', ?, ?, ?, 'delivered')""",
        (str(uuid.uuid4()), from_uri, make_agent_uri(recipient[0]["name"]), msg_id),
    )
    await db.commit()

    await audit("federation_relay", payload={
        "direction": "inbound", "from": from_uri,
        "to": to_agent_id, "message_id": msg_id,
    }, ip_address=_client_ip(request))

    return {"status": "delivered", "message_id": msg_id}
