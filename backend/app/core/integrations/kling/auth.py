"""可灵 AI JWT 鉴权：Access Key + Secret Key → Bearer Token。"""

from __future__ import annotations

import time
import hmac
import hashlib
import base64
import json


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def build_kling_jwt(*, access_key: str, secret_key: str, ttl_s: int = 1800) -> str:
    """生成可灵 API 所需的 JWT token。

    Header: {"alg":"HS256","typ":"JWT"}
    Payload: {"iss": access_key, "exp": now+ttl, "nbf": now-5}
    Signature: HMAC-SHA256(header.payload, secret_key)
    """
    now = int(time.time())
    header = _b64url(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    payload = _b64url(
        json.dumps(
            {"iss": access_key, "exp": now + ttl_s, "nbf": now - 5},
            separators=(",", ":"),
        ).encode()
    )
    signing_input = f"{header}.{payload}"
    signature = _b64url(
        hmac.new(  # type: ignore[attr-defined]
            secret_key.encode("utf-8"),
            signing_input.encode("utf-8"),
            hashlib.sha256,
        ).digest()
    )
    return f"{signing_input}.{signature}"
