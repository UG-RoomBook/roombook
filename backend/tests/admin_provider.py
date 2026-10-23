"""Deterministic external TOTP provider for isolated tests, never shipped in the app image."""

import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import jwt

from tests.identity.test_accounts import Harness

CODE = "123456"


class AdminProvider(Harness):
    def __init__(self) -> None:
        super().__init__()
        self.factors: dict[str, list[dict[str, str]]] = {}
        self.refreshes: dict[str, str] = {}
        self.fail_remove = False
        self.reject_code = False

    def transport(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path.removeprefix("/auth/v1")
        if self.unavailable:
            return super().transport(request)
        payload = json.loads(request.content) if request.content else {}
        access = request.headers.get("authorization", "").removeprefix("Bearer ")
        claims = jwt.decode(access, options={"verify_signature": False}) if access else {}
        subject = claims.get("sub", "")
        if path == "/user":
            response = super().transport(request)
            data = response.json()
            data["factors"] = self.factors.get(subject, [])
            return httpx.Response(200, json=data)
        if path.startswith("/factors"):
            self.calls.append((request.method, path, payload))
            owned = self.factors.setdefault(subject, [])
            if path == "/factors":
                enrolled = {
                    "id": str(uuid4()),
                    "friendly_name": payload["friendly_name"],
                    "factor_type": "totp",
                    "status": "unverified",
                }
                owned.append(enrolled)
                return httpx.Response(
                    200,
                    json={
                        "id": enrolled["id"],
                        "type": "totp",
                        "totp": {
                            "secret": "SYNTHETICTOTPKEY",
                            "qr_code": '<svg xmlns="http://www.w3.org/2000/svg"/>',
                            "uri": "otpauth://totp/fixture",
                        },
                    },
                )
            factor = next((f for f in owned if f["id"] == path.split("/")[2]), None)
            if not factor:
                return httpx.Response(404, json={})
            if path.endswith("/challenge"):
                return httpx.Response(200, json={"id": str(uuid4()), "type": "totp"})
            if path.endswith("/verify"):
                if self.reject_code or payload["code"] != CODE:
                    return httpx.Response(400, json={})
                factor["status"] = "verified"
                now = datetime.now(UTC)
                claims.update(
                    aal="aal2",
                    amr=[{"method": "totp", "timestamp": int(now.timestamp())}],
                    iat=int(now.timestamp()),
                    exp=int((now + timedelta(hours=1)).timestamp()),
                )
                token = jwt.encode(
                    claims, self.signing_key, algorithm="ES256", headers={"kid": "synthetic"}
                )
                refresh = str(uuid4())
                self.refreshes[refresh] = token
                return httpx.Response(
                    200,
                    json={"access_token": token, "refresh_token": refresh, "token_type": "bearer"},
                )
            if request.method == "DELETE":
                owned.remove(factor)
                return httpx.Response(503 if self.fail_remove else 200, json={})
        if path == "/token" and payload.get("refresh_token") in self.refreshes:
            return httpx.Response(
                200,
                json={
                    "access_token": self.refreshes[payload["refresh_token"]],
                    "refresh_token": payload["refresh_token"],
                    "token_type": "bearer",
                },
            )
        return super().transport(request)
