"""Asymmetric (ES256) Supabase session tokens, verified against the
project's JWKS, alongside the legacy HS256 shared-secret path."""
import asyncio
import time

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import HTTPException
from jose import jwk, jwt

from jury.api import deps
from jury.settings import Settings

KID = "test-kid"


def _keypair() -> tuple[bytes, dict]:
    private = ec.generate_private_key(ec.SECP256R1())
    private_pem = private.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    public_pem = private.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    public_jwk = jwk.construct(public_pem, "ES256").to_dict()
    public_jwk = {k: (v.decode() if isinstance(v, bytes) else v) for k, v in public_jwk.items()}
    return private_pem, {**public_jwk, "kid": KID, "use": "sig"}


def _claims() -> dict:
    return {"sub": "user-1", "aud": "authenticated", "exp": int(time.time()) + 300}


def _authenticate(token: str, settings: Settings):
    return asyncio.run(deps.get_current_user(authorization=f"Bearer {token}", app_settings=settings))


@pytest.fixture
def settings():
    return Settings(_env_file=None, NEXT_PUBLIC_SUPABASE_URL="http://supabase.test",
                    supabase_jwt_secret="hs-secret")


@pytest.fixture
def published_key(monkeypatch):
    private_pem, public_jwk = _keypair()

    async def fake_fetch(_url):
        return [public_jwk]

    monkeypatch.setattr(deps, "_fetch_jwks", fake_fetch)
    monkeypatch.setattr(deps, "_jwks_cache", {"keys": {}, "fetched_at": 0.0})
    return private_pem


def test_es256_token_signed_by_published_key_is_accepted(settings, published_key):
    token = jwt.encode(_claims(), published_key, algorithm="ES256", headers={"kid": KID})
    assert _authenticate(token, settings).id == "user-1"


def test_es256_token_signed_by_another_key_is_rejected(settings, published_key):
    forger_pem, _ = _keypair()
    token = jwt.encode(_claims(), forger_pem, algorithm="ES256", headers={"kid": KID})
    with pytest.raises(HTTPException) as exc:
        _authenticate(token, settings)
    assert exc.value.status_code == 401


def test_es256_token_with_unknown_kid_is_rejected(settings, published_key):
    token = jwt.encode(_claims(), published_key, algorithm="ES256", headers={"kid": "someone-else"})
    with pytest.raises(HTTPException) as exc:
        _authenticate(token, settings)
    assert exc.value.status_code == 401


def test_hs256_token_still_verified_against_shared_secret(settings, published_key):
    token = jwt.encode(_claims(), "hs-secret", algorithm="HS256")
    assert _authenticate(token, settings).id == "user-1"
    forged = jwt.encode(_claims(), "wrong-secret", algorithm="HS256")
    with pytest.raises(HTTPException):
        _authenticate(forged, settings)
