"""Identity verification (Ed25519 signing) — Phase 2.5 Infrastructure.

Agents can generate Ed25519 keypairs. The private key is returned once
and never stored — the agent holds it. The public key is stored and
available to anyone for verification. This is the foundation for
federation identity proofs.
"""

import base64

from fastapi import APIRouter, Depends, HTTPException

from app.auth import get_current_agent
from app.database import get_db
from app.models import KeyGenerateResponse, VerifyRequest, VerifyResponse

try:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives import serialization
    HAS_CRYPTO = True
except ImportError:
    HAS_CRYPTO = False

router = APIRouter(tags=["identity"])


def _require_crypto():
    if not HAS_CRYPTO:
        raise HTTPException(501, "Identity verification requires the 'cryptography' package")


@router.post("/agents/{agent_id}/keys", response_model=KeyGenerateResponse)
async def generate_keys(
    agent_id: str,
    agent: dict = Depends(get_current_agent),
):
    """Generate an Ed25519 keypair. Private key returned ONCE, never stored."""
    _require_crypto()
    if agent["id"] != agent_id:
        raise HTTPException(403, "Can only generate keys for yourself")

    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key()

    public_pem = public_key.public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()

    private_pem = private_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()

    db = get_db()
    # Upsert — replaces existing key if called again
    await db.execute(
        """INSERT INTO agent_keys (agent_id, public_key_pem)
           VALUES (?, ?)
           ON CONFLICT(agent_id) DO UPDATE SET
             public_key_pem = excluded.public_key_pem,
             created_at = strftime('%Y-%m-%dT%H:%M:%f', 'now')""",
        (agent_id, public_pem),
    )
    await db.commit()

    return KeyGenerateResponse(
        agent_id=agent_id,
        public_key_pem=public_pem,
        private_key_pem=private_pem,
    )


@router.get("/agents/{agent_id}/keys/public")
async def get_public_key(agent_id: str):
    """Get an agent's public key. No auth required."""
    db = get_db()
    rows = await db.execute_fetchall(
        "SELECT public_key_pem, created_at FROM agent_keys WHERE agent_id = ?",
        (agent_id,),
    )
    if not rows:
        raise HTTPException(404, "No key found for this agent")
    return {
        "agent_id": agent_id,
        "public_key_pem": rows[0]["public_key_pem"],
        "created_at": rows[0]["created_at"],
    }


@router.post("/verify", response_model=VerifyResponse)
async def verify_signature(body: VerifyRequest):
    """Verify a signature against an agent's public key. No auth required."""
    _require_crypto()
    db = get_db()
    rows = await db.execute_fetchall(
        "SELECT public_key_pem FROM agent_keys WHERE agent_id = ?",
        (body.agent_id,),
    )
    if not rows:
        raise HTTPException(404, "No key found for this agent")

    try:
        public_key = serialization.load_pem_public_key(
            rows[0]["public_key_pem"].encode()
        )
        signature = base64.b64decode(body.signature_b64)
        public_key.verify(signature, body.payload.encode())
        return VerifyResponse(valid=True, agent_id=body.agent_id)
    except Exception:
        return VerifyResponse(valid=False, agent_id=body.agent_id)
