"""
Samsung Account authentication flow.

Ported from the SamsungTracker POC to use aiohttp (Home Assistant's HTTP client)
instead of httpx. Implements the full sign-in and token acquisition process.
"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlparse, parse_qs

import aiohttp

from .const import (
    CLIENT_ID_FIND,
    CLIENT_ID_LOGIN,
    CLIENT_ID_ONECONNECT,
    ENTRY_POINT_URL,
    OSP_HEADERS,
    PATH_AUTHENTICATE,
    PATH_AUTHORISE,
    PATH_TOKEN,
)
from .crypto import (
    build_login_url,
    decrypt_login_response,
    decrypt_with_state,
    generate_code_challenge,
)

_LOGGER = logging.getLogger(__name__)


class SamsungAuthError(Exception):
    """Base exception for Samsung auth errors."""


class SamsungAuthInvalidCredentials(SamsungAuthError):
    """Raised when credentials/redirect URL is invalid."""


class SamsungAuthConnectionError(SamsungAuthError):
    """Raised when Samsung servers are unreachable."""


class SamsungAuth:
    """Handle Samsung Account OAuth2 authentication."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        country_code: str = "us",
        language: str = "en",
    ) -> None:
        self._session = session
        self._country_code = country_code
        self._language = language
        self._pending_login: dict | None = None

    async def get_entry_point(self) -> dict[str, Any]:
        """Fetch Samsung login entry point."""
        try:
            async with self._session.get(
                ENTRY_POINT_URL, headers=OSP_HEADERS
            ) as resp:
                resp.raise_for_status()
                data = await resp.json()
                return {
                    "signInURI": data["signInURI"],
                    "pkiPublicKey": data["pkiPublicKey"],
                    "chkDoNum": data.get("chkDoNum", 1),
                }
        except aiohttp.ClientError as err:
            raise SamsungAuthConnectionError(
                f"Cannot reach Samsung servers: {err}"
            ) from err

    async def start_login(self) -> str:
        """Start the Samsung login flow.

        Returns the Samsung login URL to open in a browser.
        """
        entry = await self.get_entry_point()

        login_data = build_login_url(
            sign_in_uri=entry["signInURI"],
            pki_public_key_b64=entry["pkiPublicKey"],
            chk_do_num=entry["chkDoNum"],
            country_code=self._country_code,
            language=self._language,
        )

        self._pending_login = {
            "code_verifier": login_data["code_verifier"],
            "state": login_data["state"],
            "android_id": login_data["android_id"],
        }

        return login_data["url"]

    async def complete_login(self, redirect_url: str) -> dict[str, Any]:
        """Complete the login by processing the redirect URL.

        Returns dict with user_id, email, and full token data.
        """
        if not self._pending_login:
            raise SamsungAuthError("No pending login. Call start_login() first.")

        parsed = urlparse(redirect_url)
        params = parse_qs(parsed.query)

        # Some Samsung redirects put params in the fragment
        if not params and parsed.fragment:
            params = parse_qs(parsed.fragment)

        if "code" not in params:
            raise SamsungAuthInvalidCredentials(
                f"Redirect URL missing 'code' parameter. "
                f"Available params: {list(params.keys())}. "
                f"Make sure you copied the complete redirect URL."
            )

        encrypted_code = params["code"][0]
        encrypted_auth_server = params["auth_server_url"][0]
        encrypted_state = params["state"][0]
        encrypted_email = params["retValue"][0]

        state = self._pending_login["state"]
        code_verifier = self._pending_login["code_verifier"]
        android_id = self._pending_login["android_id"]

        # Decrypt the state first, then use it to decrypt the rest
        decrypted_state = decrypt_login_response(encrypted_state, state)
        auth_code = decrypt_with_state(encrypted_code, decrypted_state)
        auth_server_url = decrypt_with_state(encrypted_auth_server, decrypted_state)
        email = decrypt_with_state(encrypted_email, decrypted_state)

        _LOGGER.info("Login successful for %s", email)

        if auth_server_url and not auth_server_url.startswith("http"):
            auth_server_url = f"https://{auth_server_url}"

        # Step 1: exchange auth code for userauth_token
        user_auth = await self._authenticate(
            auth_server_url, auth_code, code_verifier, email, android_id
        )

        user_id = user_auth["userId"]
        user_auth_token = user_auth["userauth_token"]

        # Step 2+3: Get SmartThings token (scope=iot.client)
        st_tokens = await self._get_api_token(
            auth_server_url, user_auth_token,
            CLIENT_ID_ONECONNECT, "iot.client",
            email, android_id, code_verifier,
        )

        # Step 2+3: Get Find token (scope=offline.access)
        find_tokens = await self._get_api_token(
            auth_server_url, user_auth_token,
            CLIENT_ID_FIND, "offline.access",
            email, android_id, code_verifier,
        )

        self._pending_login = None

        return {
            "user_id": user_id,
            "email": email,
            "auth_server_url": auth_server_url,
            "user_auth_token": user_auth_token,
            "android_id": android_id,
            "code_verifier": code_verifier,
            "smartthings": {
                "access_token": st_tokens["access_token"],
                "refresh_token": st_tokens["refresh_token"],
            },
            "find": {
                "access_token": find_tokens["access_token"],
                "refresh_token": find_tokens["refresh_token"],
            },
        }

    async def refresh_token(
        self, tokens: dict[str, Any], api: str = "smartthings"
    ) -> dict[str, Any]:
        """Refresh access token for the given API.

        Returns updated tokens dict.
        """
        client_id = CLIENT_ID_ONECONNECT if api == "smartthings" else CLIENT_ID_FIND
        api_tokens = tokens[api]
        auth_server_url = tokens["auth_server_url"]

        try:
            token_url = f"{auth_server_url}{PATH_TOKEN}"
            data = {
                "grant_type": "refresh_token",
                "client_id": client_id,
                "refresh_token": api_tokens["refresh_token"],
            }
            async with self._session.post(
                token_url, data=data, headers=OSP_HEADERS
            ) as resp:
                resp.raise_for_status()
                new_tokens = await resp.json()

            api_tokens["access_token"] = new_tokens["access_token"]
            api_tokens["refresh_token"] = new_tokens["refresh_token"]
            _LOGGER.info("Refreshed %s token successfully", api)
            return tokens

        except Exception:
            _LOGGER.warning(
                "Refresh token failed for %s, re-authenticating via userauth_token",
                api,
            )
            new_api_tokens = await self._get_api_token(
                auth_server_url,
                tokens["user_auth_token"],
                client_id,
                "iot.client" if api == "smartthings" else "offline.access",
                tokens["email"],
                tokens["android_id"],
                tokens.get("code_verifier", ""),
            )
            api_tokens["access_token"] = new_api_tokens["access_token"]
            api_tokens["refresh_token"] = new_api_tokens["refresh_token"]
            return tokens

    async def _authenticate(
        self,
        auth_server_url: str,
        auth_code: str,
        code_verifier: str,
        email: str,
        android_id: str,
    ) -> dict[str, Any]:
        """Step 1: Exchange login auth code for userauth_token."""
        url = f"{auth_server_url}{PATH_AUTHENTICATE}"
        data = {
            "grant_type": "authorization_code",
            "serviceType": "M",
            "code": auth_code,
            "client_id": CLIENT_ID_LOGIN,
            "code_verifier": code_verifier,
            "username": email,
            "physical_address_text": android_id,
        }
        try:
            async with self._session.post(
                url, data=data, headers=OSP_HEADERS
            ) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    raise SamsungAuthInvalidCredentials(
                        f"Authentication failed: {resp.status} {text}"
                    )
                return await resp.json()
        except aiohttp.ClientError as err:
            raise SamsungAuthConnectionError(str(err)) from err

    async def _get_api_token(
        self,
        auth_server_url: str,
        user_auth_token: str,
        client_id: str,
        scope: str,
        email: str,
        android_id: str,
        code_verifier: str,
    ) -> dict[str, Any]:
        """Steps 2+3: Get API access_token + refresh_token."""
        new_verifier, new_challenge = generate_code_challenge()

        # Step 2: GET authorize
        auth_url = f"{auth_server_url}{PATH_AUTHORISE}"
        auth_params = {
            "response_type": "code",
            "serviceType": "M",
            "client_id": client_id,
            "code_challenge_method": "S256",
            "childAccountSupported": "Y",
            "userauth_token": user_auth_token,
            "code_challenge": new_challenge,
            "physical_address_text": android_id,
            "scope": scope,
            "login_id": email,
        }
        try:
            async with self._session.get(
                auth_url, params=auth_params, headers=OSP_HEADERS
            ) as resp:
                resp.raise_for_status()
                auth_data = await resp.json()
        except aiohttp.ClientError as err:
            raise SamsungAuthConnectionError(str(err)) from err

        # Handle privacyAccepted="N" case
        if auth_data.get("code") is None and auth_data.get("privacyAccepted") == "N":
            new_verifier2, new_challenge2 = generate_code_challenge()
            auth_params["code_challenge"] = new_challenge2
            del auth_params["login_id"]
            async with self._session.get(
                auth_url, params=auth_params, headers=OSP_HEADERS
            ) as resp:
                resp.raise_for_status()
                auth_data = await resp.json()
            new_verifier = new_verifier2

        auth_code = auth_data.get("code")
        if not auth_code:
            raise SamsungAuthError(f"Authorize returned no code: {auth_data}")

        # Step 3: POST token
        token_url = f"{auth_server_url}{PATH_TOKEN}"
        token_data = {
            "grant_type": "authorization_code",
            "client_id": client_id,
            "code": auth_code,
            "code_verifier": new_verifier,
            "physical_address_text": android_id,
        }
        try:
            async with self._session.post(
                token_url, data=token_data, headers=OSP_HEADERS
            ) as resp:
                resp.raise_for_status()
                return await resp.json()
        except aiohttp.ClientError as err:
            raise SamsungAuthConnectionError(str(err)) from err
