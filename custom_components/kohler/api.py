"""Kohler Konnect API client."""
from __future__ import annotations

import base64
import hashlib
import json as _json
import logging
import os
import secrets
import ssl
import tempfile
import time
from typing import Any
from urllib.parse import urlencode

import requests

from .const import (
    API_BASE,
    B2C_CLIENT_ID,
    B2C_OAUTH_AUTHORIZE_URL,
    B2C_OAUTH_REDIRECT_URI,
    B2C_OAUTH_TOKEN_URL,
    B2C_SCOPE,
    B2C_TOKEN_URL,
    SERVICE_TOKEN_APIM_KEY,
    SERVICE_TOKEN_URL,
    SKU_GCS,
)

_LOGGER = logging.getLogger(__name__)


class ReauthRequired(Exception):
    """Raised when the stored OAuth refresh token is no longer valid."""


def _extract_oid(jwt_token: str) -> str | None:
    """Decode a JWT payload and return the oid (or sub) claim."""
    payload = jwt_token.split(".")[1]
    payload += "=" * (-len(payload) % 4)
    claims = _json.loads(base64.b64decode(payload))
    return claims.get("oid") or claims.get("sub")


def generate_pkce_pair() -> tuple[str, str]:
    """Return (code_verifier, code_challenge) for S256 PKCE."""
    verifier = secrets.token_urlsafe(64)[:128]
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .rstrip(b"=")
        .decode()
    )
    return verifier, challenge


def build_authorize_url(code_challenge: str, state: str) -> str:
    """Build the B2C authorize URL for the OAuth + PKCE sign-in flow."""
    params = {
        "client_id": B2C_CLIENT_ID,
        "response_type": "code",
        "redirect_uri": B2C_OAUTH_REDIRECT_URI,
        "scope": B2C_SCOPE,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "state": state,
    }
    return f"{B2C_OAUTH_AUTHORIZE_URL}?{urlencode(params)}"


def exchange_code_for_tokens(code: str, code_verifier: str) -> dict[str, Any]:
    """Exchange an authorization code for an access + refresh token pair."""
    resp = requests.post(
        B2C_OAUTH_TOKEN_URL,
        data={
            "grant_type": "authorization_code",
            "client_id": B2C_CLIENT_ID,
            "code": code,
            "redirect_uri": B2C_OAUTH_REDIRECT_URI,
            "code_verifier": code_verifier,
            "scope": B2C_SCOPE,
        },
        timeout=15,
    )
    if resp.status_code >= 400:
        raise RuntimeError(
            f"Token exchange failed: {resp.status_code} {resp.text}"
        )
    return resp.json()

# The mTLS client certificate (embedded from app_certificate.p12)
# CN=apim-prod-us, valid through Aug 2026
_CERT_PEM = """\
-----BEGIN CERTIFICATE-----
MIIDZzCCAk6gAwIBAgIBADANBgkqhkiG9w0BAQsFADBNMQswCQYDVQQGEwJ1czES
MBAGA1UECAwJV2lzY29uc2luMRMwEQYDVQQKDApLb2hsZXIgQ28uMRUwEwYDVQQD
DAxhcGltLXByb2QtdXMwHhcNMjUwNzE2MDUxNzA5WhcNMjYwODE4MDUxNzA5WjBN
MQswCQYDVQQGEwJ1czESMBAGA1UECAwJV2lzY29uc2luMRMwEQYDVQQKDApLb2hs
ZXIgQ28uMRUwEwYDVQQDDAxhcGltLXByb2QtdXMwggEjMA0GCSqGSIb3DQEBAQUA
A4IBEAAwggELAoIBAgC+Td5ZOsPeiU97tTNxvhS32u3L6Rt6T4FmTuqhu8aX04/i
IuQrYG47i2eU5DFdfKnMiqwK4nkYyG53oYHcSmC451QLY8he25mvZlQtaz32OZHj
W8FMgeg9yIDN1irxoYqvo6R8u3gHaJ/EXY8VBepiGKmwSqngbswqf+w3eK69AKmE
po91mKu6MBt6e8G5aDj2Kfirlbdcb0y8CXR/qFZoN9/33BucJwdsu6//TWFUvZT9
eXDc/jtlD7c3iFkMXx+qOHhbvKNqZuQXz1PWNmT/aJErVxKl4B1zNGpJrq+R/iUz
zC7oBMqzIg0UnywnqtcR9qZ7YcHN7LGmQBpdMM4ZuwIDAQABo1AwTjAdBgNVHQ4E
FgQUQzM6NsyL5zzg6ePWKNbT16nWAqcwHwYDVR0jBBgwFoAUQzM6NsyL5zzg6ePW
KNbT16nWAqcwDAYDVR0TBAUwAwEB/zANBgkqhkiG9w0BAQsFAAOCAQIAg88fLeuq
bYbdwa600xsV4VbJiD5R7704HWrhpp9oYmAl4DL2rCUP7mvl0T7zqrZgYzY8G4JP
6Uf2e4M8qFf8XfEvytR3+tbZW/DL5hP7fYIN/IaS7NH/G8Hc9RLqW1Tu0V2y3Ote
QhtWL9VF5MWHpBKwJMpYg+XVRtzF+4qpEXSJewGm/wHTAV6I6n+nEFcPxsCH78TA
7QJGeS+IsPqEnpAXAZXLPQTuJ0DKEMre7Z3aL7dux+pzEGIoUw/3AtNWBgun2UPu
oSryHNbhGyXWg2pgkTEjPZXZ4UwTB4EkpPY7+QKHwsMzuZFbrWGBlaJ/icnYXdiT
QNur6oOVOCS28x4=
-----END CERTIFICATE-----
"""
_KEY_PEM = """\
-----BEGIN PRIVATE KEY-----
MIIEwQIBADANBgkqhkiG9w0BAQEFAASCBKswggSnAgEAAoIBAgC+Td5ZOsPeiU97
tTNxvhS32u3L6Rt6T4FmTuqhu8aX04/iIuQrYG47i2eU5DFdfKnMiqwK4nkYyG53
oYHcSmC451QLY8he25mvZlQtaz32OZHjW8FMgeg9yIDN1irxoYqvo6R8u3gHaJ/E
XY8VBepiGKmwSqngbswqf+w3eK69AKmEpo91mKu6MBt6e8G5aDj2Kfirlbdcb0y8
CXR/qFZoN9/33BucJwdsu6//TWFUvZT9eXDc/jtlD7c3iFkMXx+qOHhbvKNqZuQX
z1PWNmT/aJErVxKl4B1zNGpJrq+R/iUzzC7oBMqzIg0UnywnqtcR9qZ7YcHN7LGm
QBpdMM4ZuwIDAQABAoIBAS0LEU3dcu8BYSbOxNZvP0glMZPKIQ7aMq6cjzyozWCy
WqQTzh3WPUEqxeGgAW83Spl3WTFaWX9cMYlvWOVjVXFuj54CiDKrl7zEY7g8YfYd
ukIuPZp2RRoakyIlRxTaP5FDEnPTi511ThuUaYF4XPnLDJ8FjR/qGbkVfjvC/NkP
gIN/T7yyKoxepg6LI7aDvZixSeThr8JIz7yx5i+aCsmX6ZPuxKjwpWvIxMZBZdXM
A/0DUrJrqkTxzS2Y+dAexdltiat5fYsLiwu5wsBLSWfvGzPwK8k57GFTIhuIbtg2
JfQW1TSym2rZmD7AZDrtxnGPbxreyb1/Fx2armZ00qhBAoGBDuX+LgqOsc6hMDG5
nybJOftMQS3/JLg6DxhTLkAVDD/6TIX5J0NW7JjeISYRjIwSCakcAtrlKczuNyCU
VQMXDOG11jcsR0lZlrpU9oQDQFdh2eTPVelEOL1DVq18i4usZA83lYtnKrBxB8Rg
+skks+G2rnQwdVaBYWOW+dGCt1ZvAoGBDMYBLmO+/1t/TMQvBRp8Vk78TeY58ggC
xe6tHfSUkg1DM2Xdy6/+vMBa+WkKhIZcsd1JwzPmKTeNVMt23TPI1UFkFYR+yJSO
uFGl9WHPsu2YjcTS/0FVbjqi/frRMZzhKnafRZk4GDJnCN9ZeSMULPgsavxE5QTO
Y7kPHiZ+ind1AoGBDECIcESuZPuRA5lhFclH4y8O3ut80C3RUWinv3lj1dcneJcU
930hlyGAS7KK7BKlIty39IEfxOiLXzqjweXwpt9YMvrcpyNjUdma1cBrDBbQmejZ
ucVEHYVIQ5gYvIn5E7CP/aPPDARecAzH1HZmgKg3G/DhiR3C+Nx15Kyv2yZxAoGB
AJOKiBpOCt2I/+C2MmfAhnBn5+fkY2xDG8UqIHjhnzlj99S3zjHxr3iKYkiABfy9
//R5GIql7uQnx1Sq10432I9rwaDJy6kQS3a7oze3lF4uDO99ibDb9u5EXmtLtw5a
Bn11sEE6i7Tyey8ArXuMtH66GlWpkh/GZC98ZCLegMblAoGBB9dZOue38ETffErG
ZJk0Qfjszh19lwO/TarCG6cd488qzRWQl/FsTuCnHxjW6E1jEVCN32jH8uOY0+Tw
jcbJAd3w+9RdOak4IFc8KuRHI/HYbmcGGXULEVLa3DYXSkPtAk3xXjqp/z4nkGZW
hX7Z251Uvyc+Oy+tI9fCtevJU4wY
-----END PRIVATE KEY-----
"""

# Paths on disk (written at runtime)
_CERT_PATH: str | None = None
_KEY_PATH: str | None = None


def _ensure_cert_files() -> tuple[str, str]:
    """Write embedded cert/key to temp files if not already done."""
    global _CERT_PATH, _KEY_PATH
    if _CERT_PATH and _KEY_PATH and os.path.exists(_CERT_PATH):
        return _CERT_PATH, _KEY_PATH

    # Use existing extracted files if present (dev mode)
    if os.path.exists("/tmp/kohler_client.crt"):
        _CERT_PATH = "/tmp/kohler_client.crt"
        _KEY_PATH = "/tmp/kohler_client.key"
        return _CERT_PATH, _KEY_PATH

    # Write embedded cert/key to temp files
    cert_file = tempfile.NamedTemporaryFile(
        delete=False, suffix=".crt", mode="w"
    )
    cert_file.write(_CERT_PEM)
    cert_file.close()

    key_file = tempfile.NamedTemporaryFile(
        delete=False, suffix=".key", mode="w"
    )
    key_file.write(_KEY_PEM)
    key_file.close()

    _CERT_PATH = cert_file.name
    _KEY_PATH = key_file.name
    return _CERT_PATH, _KEY_PATH


class KohlerKonnectAPI:
    """Client for the Kohler Konnect API."""

    def __init__(
        self,
        *,
        username: str | None = None,
        password: str | None = None,
        refresh_token: str | None = None,
    ) -> None:
        self._username = username
        self._password = password
        self._refresh_token = refresh_token
        self._user_token: str | None = None
        self._token_expires_at: float = 0.0
        self._apim_key: str | None = None
        self._tenant_id: str | None = None
        self._devices: list[dict] = []
        self._mode = "oauth" if refresh_token else "ropc"

    @property
    def refresh_token(self) -> str | None:
        """Return the current refresh token (may have rotated since init)."""
        return self._refresh_token

    def _session(self) -> requests.Session:
        """Build a requests session with mTLS client cert."""
        cert, key = _ensure_cert_files()
        s = requests.Session()
        s.cert = (cert, key)
        s.verify = True  # verify server cert normally
        return s

    def _headers(self) -> dict[str, str]:
        self._ensure_fresh_token()
        return {
            "Authorization": f"Bearer {self._user_token}",
            "Ocp-Apim-Subscription-Key": self._apim_key,
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    def _ensure_fresh_token(self) -> None:
        """Refresh the user token if it's near expiry (OAuth mode only)."""
        if self._mode != "oauth":
            return
        if self._user_token and time.time() < self._token_expires_at:
            return
        self._fetch_user_token_oauth()

    # ------------------------------------------------------------------ #
    # Auth                                                                 #
    # ------------------------------------------------------------------ #

    def _fetch_service_token(self) -> None:
        """Fetch the service token + real APIM key (no user needed)."""
        s = self._session()
        resp = s.get(
            SERVICE_TOKEN_URL,
            headers={"Ocp-Apim-Subscription-Key": SERVICE_TOKEN_APIM_KEY},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        self._apim_key = data["apim_key"]
        _LOGGER.debug("Service token fetched, APIM key acquired")

    def _fetch_user_token(self) -> None:
        """Fetch user access token via legacy ROPC flow."""
        resp = requests.post(
            B2C_TOKEN_URL,
            data={
                "grant_type": "password",
                "client_id": B2C_CLIENT_ID,
                "username": self._username,
                "password": self._password,
                "scope": B2C_SCOPE,
            },
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        self._user_token = data["access_token"]
        self._tenant_id = _extract_oid(self._user_token)
        _LOGGER.debug("User token fetched (ROPC), tenant_id=%s", self._tenant_id)

    def _fetch_user_token_oauth(self) -> None:
        """Refresh the user access token using the stored refresh_token."""
        resp = requests.post(
            B2C_OAUTH_TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "client_id": B2C_CLIENT_ID,
                "refresh_token": self._refresh_token,
                "scope": B2C_SCOPE,
            },
            timeout=15,
        )
        if resp.status_code == 400:
            try:
                body = resp.json()
            except ValueError:
                body = {}
            if body.get("error") == "invalid_grant":
                raise ReauthRequired(
                    body.get("error_description", "refresh_token rejected")
                )
        resp.raise_for_status()
        data = resp.json()
        self._user_token = data["access_token"]
        self._token_expires_at = (
            time.time() + int(data.get("expires_in", 3600)) - 60
        )
        if "refresh_token" in data:
            self._refresh_token = data["refresh_token"]
        self._tenant_id = _extract_oid(self._user_token)
        _LOGGER.debug("User token fetched (OAuth), tenant_id=%s", self._tenant_id)

    def apply_oauth_tokens(self, token_response: dict[str, Any]) -> None:
        """Seed this client from a fresh authorization_code token response."""
        self._mode = "oauth"
        self._user_token = token_response["access_token"]
        self._refresh_token = token_response.get("refresh_token")
        self._token_expires_at = (
            time.time() + int(token_response.get("expires_in", 3600)) - 60
        )
        self._tenant_id = _extract_oid(self._user_token)

    def authenticate(self) -> None:
        """Full auth: service token + user token."""
        self._fetch_service_token()
        if self._mode == "oauth":
            self._fetch_user_token_oauth()
        else:
            self._fetch_user_token()

    # ------------------------------------------------------------------ #
    # Device discovery                                                     #
    # ------------------------------------------------------------------ #

    def get_devices(self) -> list[dict]:
        """Return the list of registered devices."""
        s = self._session()
        resp = s.get(
            f"{API_BASE}/devices/api/v1/device-management/customer-device/{self._tenant_id}",
            headers=self._headers(),
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        self._devices = []
        for home in data.get("customerHome", []):
            for device in home.get("devices", []):
                device["homeId"] = home["homeId"]
                device["homeName"] = home["homeName"]
                self._devices.append(device)
        return self._devices

    # ------------------------------------------------------------------ #
    # State                                                                #
    # ------------------------------------------------------------------ #

    def get_gcs_advanced_state(self, device_id: str) -> dict[str, Any]:
        """Get the full advanced state of a GCS (Anthem) shower."""
        s = self._session()
        resp = s.get(
            f"{API_BASE}/devices/api/v1/device-management/gcs-state/gcsadvancestate/{device_id}",
            headers=self._headers(),
            timeout=15,
        )
        resp.raise_for_status()
        body = resp.json()
        _LOGGER.debug("gcsadvancestate raw response: %s", body)
        return body

    def get_evo_state(self, device_id: str) -> dict[str, Any]:
        """Get the EVO state (connection state, error state)."""
        s = self._session()
        resp = s.get(
            f"{API_BASE}/devices/api/v1/device-management/evo-state/{device_id}",
            headers=self._headers(),
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()

    def get_presets(self, tenant_id: str | None = None) -> dict[str, Any]:
        """Get all presets and experiences for the customer."""
        tid = tenant_id or self._tenant_id
        s = self._session()
        resp = s.get(
            f"{API_BASE}/devices/api/v1/device-management/customer-experience/{tid}",
            headers=self._headers(),
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()

    def get_all_state(self) -> dict[str, Any]:
        """Fetch all state needed for HA entities."""
        if not self._devices:
            self.get_devices()

        result = {}
        for device in self._devices:
            did = device["deviceId"]
            sku = device.get("sku", "")
            if sku == SKU_GCS:
                result[did] = {
                    "device": device,
                    "advanced_state": self.get_gcs_advanced_state(did),
                    "evo_state": self.get_evo_state(did),
                }
        return result

    # ------------------------------------------------------------------ #
    # Commands                                                             #
    # ------------------------------------------------------------------ #

    def start_warmup(self, device_id: str) -> dict[str, Any]:
        """Start shower warmup (pre-heat, no water running)."""
        s = self._session()
        resp = s.post(
            f"{API_BASE}/platform/api/v1/commands/gcs/warmup",
            headers=self._headers(),
            json={
                "deviceId": device_id,
                "tenantId": self._tenant_id,
                "sku": SKU_GCS,
            },
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()

    def start_preset(self, device_id: str, preset_id: str) -> dict[str, Any]:
        """Start a saved preset."""
        s = self._session()
        resp = s.post(
            f"{API_BASE}/platform/api/v1/commands/gcs/preset",
            headers=self._headers(),
            json={
                "deviceId": device_id,
                "tenantId": self._tenant_id,
                "sku": SKU_GCS,
                "presetOrExperienceId": preset_id,
            },
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()

    def stop_shower(self, device_id: str) -> dict[str, Any]:
        """Stop the shower."""
        s = self._session()
        resp = s.post(
            f"{API_BASE}/platform/api/v1/commands/gcs/turn_off",
            headers=self._headers(),
            json={
                "deviceId": device_id,
                "tenantId": self._tenant_id,
                "sku": SKU_GCS,
            },
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()

    def write_outlet_config(
        self,
        device_id: str,
        valve_index: str = "Valve1",
        outlet: str = "2",
        temperature: float = 39.4,
        flow: int = 19,
    ) -> dict[str, Any]:
        """Set a specific outlet temperature and flow."""
        s = self._session()
        resp = s.post(
            f"{API_BASE}/platform/api/v1/commands/gcs/writeoutletconfig",
            headers=self._headers(),
            json={
                "deviceId": device_id,
                "tenantId": self._tenant_id,
                "sku": SKU_GCS,
                "valveIndex": valve_index,
                "outletIndex": outlet,
                "temperatureSetpoint": str(temperature),
                "flowSetpoint": str(flow),
            },
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()
