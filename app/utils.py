"""Shared request utilities."""

from fastapi import Request


def client_ip(request: Request) -> str:
    """Return the real client IP address.

    Resolution order:
    1. ``Fly-Client-IP`` — set by Fly.io's edge proxy; cannot be prepended or
       forged by the remote client. Correct for all Fly.io deployments.
    2. ``request.client.host`` — the actual TCP remote address. Correct for
       local development (no reverse proxy). On Fly.io this would be an
       internal 10.x.x.x address, so Fly-Client-IP takes precedence.

    We intentionally do NOT parse ``X-Forwarded-For``. XFF can be prepended
    by the remote client (e.g. ``X-Forwarded-For: 1.2.3.4, real_client``),
    which would let an attacker bypass IP-based rate limits by cycling
    arbitrary fake IPs. See audit finding H-1.
    """
    fly_ip = request.headers.get("fly-client-ip")
    if fly_ip:
        return fly_ip.strip()
    return request.client.host if request.client else "unknown"
