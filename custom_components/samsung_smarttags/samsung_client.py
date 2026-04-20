"""
SmartThings Installed Apps Proxy client for Samsung SmartTags.

Ported from the SamsungTracker POC to use aiohttp.
Handles device discovery and location fetching through the SmartThings proxy API.
"""

from __future__ import annotations

import base64
import json
import logging
import uuid
from typing import Any

import aiohttp

from .const import (
    FME_PLUGIN_ID,
    SMARTTHINGS_API,
    SMARTTHINGS_CLIENT_VERSION,
    ST_HEADERS,
)
from .crypto import decrypt_e2e_location

_LOGGER = logging.getLogger(__name__)


class SmartTagsClientError(Exception):
    """Base exception for SmartTags client errors."""


class SmartTagsAuthError(SmartTagsClientError):
    """Raised when authentication fails (401)."""


class SmartTagsClient:
    """Client to communicate with Samsung SmartThings for Smart Tag tracking."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        tokens: dict[str, Any],
        e2e_pin: str = "",
    ) -> None:
        self._session = session
        self._tokens = tokens
        self._e2e_pin = e2e_pin
        self._installed_app_id: str | None = None

    @property
    def tokens(self) -> dict[str, Any]:
        """Return current tokens."""
        return self._tokens

    def update_tokens(self, tokens: dict[str, Any]) -> None:
        """Update stored tokens after refresh."""
        self._tokens = tokens

    def _get_headers(self) -> dict[str, str]:
        """Build request headers with auth token."""
        token = self._tokens["smartthings"]["access_token"]
        return {
            **ST_HEADERS,
            "Authorization": f"Bearer {token}",
            "X-St-Correlation": str(uuid.uuid4()),
        }

    def _build_client_object(self) -> dict[str, Any]:
        """Build the client metadata for proxy requests."""
        return {
            "displayMode": "DARK",
            "language": "en",
            "mobileDeviceId": self._tokens["android_id"],
            "os": "Android",
            "samsungAccountId": self._tokens["user_id"],
            "supportedTemplates": [
                "BASIC_V1", "BASIC_V2", "BASIC_V3", "BASIC_V4",
                "BASIC_V5", "BASIC_V6", "BASIC_V7",
            ],
            "timeZoneOffset": "UTC+00:00",
            "version": SMARTTHINGS_CLIENT_VERSION,
        }

    async def _ensure_installed_app_id(self) -> None:
        """Find the installed app ID for the FME plugin."""
        if self._installed_app_id:
            return

        headers = self._get_headers()
        async with self._session.get(
            f"{SMARTTHINGS_API}/installedapps",
            params={"allowed": "true"},
            headers=headers,
        ) as resp:
            if resp.status == 401:
                raise SmartTagsAuthError("SmartThings token expired")
            resp.raise_for_status()
            data = await resp.json()

        for item in data.get("items", []):
            ui = item.get("ui", {})
            if ui.get("pluginId") == FME_PLUGIN_ID:
                self._installed_app_id = item["installedAppId"]
                _LOGGER.debug("Found FME installed app: %s", self._installed_app_id)
                return

        raise SmartTagsClientError(
            "FME plugin not found. Make sure Samsung Find is set up on your account."
        )

    async def _proxy_request(
        self,
        method: str,
        uri: str,
        extra_uri: str | None = None,
        body: dict | None = None,
        additional_params: dict | None = None,
    ) -> Any:
        """Make a request through the SmartThings installed apps proxy."""
        await self._ensure_installed_app_id()

        access_token = self._tokens["smartthings"]["access_token"]

        parameters: dict[str, Any] = {
            "requester": self._tokens["user_id"],
            "clientType": "aPlugin",
            "method": method,
            "encodedHeaders": "",
            "requesterToken": access_token,
            "encodedBody": "",
            "clientVersion": "1",
            "uri": uri,
        }

        if extra_uri:
            parameters["extraUri"] = extra_uri

        if body is not None:
            encoded_body = base64.b64encode(json.dumps(body).encode()).decode()
            parameters["encodedBody"] = encoded_body

        if additional_params:
            parameters.update(additional_params)

        payload = {
            "client": self._build_client_object(),
            "parameters": parameters,
        }

        headers = self._get_headers()
        url = f"{SMARTTHINGS_API}/installedapps/{self._installed_app_id}/execute"

        async with self._session.post(url, json=payload, headers=headers) as resp:
            if resp.status == 401:
                raise SmartTagsAuthError("SmartThings token expired")
            resp.raise_for_status()
            proxy_resp = await resp.json()

        status_code = proxy_resp.get("statusCode", 200)
        if status_code >= 400:
            raise SmartTagsClientError(
                f"Proxy error: {status_code} - {proxy_resp.get('message', '')}"
            )

        message = proxy_resp.get("message", "")
        if isinstance(message, str) and message:
            try:
                return json.loads(message)
            except json.JSONDecodeError:
                return message
        return message

    async def get_devices(self) -> list[dict[str, Any]]:
        """Get all FMM devices including trackers."""
        result = await self._proxy_request("GET", "/devices")
        if isinstance(result, dict):
            return result.get("devices", [])
        return []

    async def get_tracker_list(self) -> list[dict[str, Any]]:
        """Get only tracker-type devices."""
        devices = await self.get_devices()
        return [d for d in devices if d.get("locationType") == "TRACKER"]

    async def get_location(self, device_id: str) -> dict[str, Any]:
        """Get current location for a tag (includes key pairs for E2E)."""
        result = await self._proxy_request(
            "GET",
            "/trackers/geolocation",
            additional_params={"stDids": device_id},
        )
        return result if isinstance(result, dict) else {}

    async def get_location_history(
        self,
        device_id: str,
        start_time: int | None = None,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        """Get location history for a tag since start_time (ms epoch).

        Returns list of geolocation dicts ordered ascending by time.
        """
        query = f"?order=asc&isSummary=false&limit={limit}"
        if start_time is not None:
            query += f"&startTime={start_time}"

        result = await self._proxy_request(
            "GET",
            "/trackerapi",
            extra_uri=f"/trackers/{device_id}/geolocations{query}",
        )
        if isinstance(result, dict):
            return result.get("geolocations") or result.get("geoLocations", [])
        return []

    async def get_all_tag_data(self) -> dict[str, dict[str, Any]]:
        """Fetch all tracker devices and their current locations (single point).

        Returns dict keyed by device_id with tag info + location data.
        """
        trackers = await self.get_tracker_list()
        result: dict[str, dict[str, Any]] = {}

        for tracker in trackers:
            device_id = tracker.get("stDid") or tracker.get("deviceId", "")
            if not device_id:
                continue

            name = tracker.get("stDevName", device_id)
            model_name = tracker.get("modelName", "SmartTag")

            tag_data: dict[str, Any] = {
                "name": name,
                "model_name": model_name,
                "device_id": device_id,
                "latitude": None,
                "longitude": None,
                "accuracy": None,
                "battery_level": None,
            }

            try:
                loc_result = await self.get_location(device_id)
                key_pairs = loc_result.get("keyPairs", [])

                items = loc_result.get("items", [])
                for item in items:
                    if item.get("deviceId") != device_id:
                        continue

                    geos = item.get("geolocations") or item.get("geoLocations", [])
                    if not geos:
                        continue

                    # Take the most recent geolocation
                    geo = geos[-1] if geos else None
                    if not geo:
                        continue

                    lat_raw = geo.get("latitude", "0")
                    lon_raw = geo.get("longitude", "0")

                    try:
                        lat, lon = float(lat_raw), float(lon_raw)
                    except (ValueError, TypeError):
                        # Attempt E2E decryption
                        lat, lon = self._decrypt_location(
                            str(lat_raw), str(lon_raw), key_pairs
                        )

                    if lat == 0.0 and lon == 0.0:
                        continue

                    tag_data["latitude"] = lat
                    tag_data["longitude"] = lon
                    tag_data["accuracy"] = self._safe_float(geo.get("accuracy"))
                    tag_data["battery_level"] = (
                        geo.get("battery") or geo.get("batteryLevel")
                    )

            except Exception:
                _LOGGER.exception("Failed to get location for %s", device_id)

            result[device_id] = tag_data

        return result

    def _decrypt_location(
        self, lat: str, lon: str, key_pairs: list[dict]
    ) -> tuple[float, float]:
        """Try to decrypt E2E-encrypted coordinates."""
        if not self._e2e_pin:
            _LOGGER.warning("Encrypted location but no E2E PIN configured")
            return 0.0, 0.0

        if not key_pairs:
            _LOGGER.warning("No key pairs available for decryption")
            return 0.0, 0.0

        kp = key_pairs[0]
        user_id = kp.get("userId", "")
        private_key_b64 = kp["privateKey"]
        iv_b64 = kp["iv"]

        try:
            return decrypt_e2e_location(
                lat, lon, private_key_b64, iv_b64,
                self._e2e_pin, user_id,
            )
        except Exception:
            _LOGGER.exception("E2E decryption failed")
            return 0.0, 0.0

    @staticmethod
    def _safe_float(val: Any) -> float | None:
        """Safely convert a value to float."""
        if val is None:
            return None
        try:
            return float(val)
        except (ValueError, TypeError):
            return None

    def _parse_geo(
        self, geo: dict[str, Any], key_pairs: list[dict]
    ) -> dict[str, Any] | None:
        """Parse a single geolocation entry into a standard dict."""
        lat_raw = geo.get("latitude", "0")
        lon_raw = geo.get("longitude", "0")

        try:
            lat, lon = float(lat_raw), float(lon_raw)
        except (ValueError, TypeError):
            lat, lon = self._decrypt_location(
                str(lat_raw), str(lon_raw), key_pairs
            )

        if lat == 0.0 and lon == 0.0:
            return None

        timestamp_ms = geo.get("lastUpdateTime")
        if isinstance(timestamp_ms, str):
            try:
                timestamp_ms = int(timestamp_ms)
            except (ValueError, TypeError):
                timestamp_ms = None

        return {
            "latitude": lat,
            "longitude": lon,
            "accuracy": self._safe_float(geo.get("accuracy")),
            "battery_level": geo.get("battery") or geo.get("batteryLevel"),
            "timestamp_ms": timestamp_ms,
        }

    async def get_all_tag_data_with_history(
        self,
        last_poll_timestamps: dict[str, int],
    ) -> dict[str, dict[str, Any]]:
        """Fetch all tracker devices with location history since last poll.

        Returns dict keyed by device_id with:
          - name, model_name, device_id
          - locations: list of {latitude, longitude, accuracy, battery_level, timestamp_ms}
                       ordered ascending by time
        """
        trackers = await self.get_tracker_list()
        result: dict[str, dict[str, Any]] = {}

        for tracker in trackers:
            device_id = tracker.get("stDid") or tracker.get("deviceId", "")
            if not device_id:
                continue

            name = tracker.get("stDevName", device_id)
            model_name = tracker.get("modelName", "SmartTag")

            tag_data: dict[str, Any] = {
                "name": name,
                "model_name": model_name,
                "device_id": device_id,
                "locations": [],
            }

            try:
                # Get current location (for E2E key pairs)
                loc_result = await self.get_location(device_id)
                key_pairs = loc_result.get("keyPairs", [])

                # Determine start_time for history fetch
                start_time = last_poll_timestamps.get(device_id)

                # Fetch history since last poll
                history_geos = await self.get_location_history(
                    device_id, start_time=start_time
                )

                locations: list[dict[str, Any]] = []
                for geo in history_geos:
                    parsed = self._parse_geo(geo, key_pairs)
                    if parsed:
                        locations.append(parsed)

                # Also include current location from the geolocation endpoint
                # (may be newer than last history entry)
                items = loc_result.get("items", [])
                for item in items:
                    if item.get("deviceId") != device_id:
                        continue
                    geos = item.get("geolocations") or item.get("geoLocations", [])
                    for geo in geos:
                        parsed = self._parse_geo(geo, key_pairs)
                        if parsed:
                            locations.append(parsed)

                # Deduplicate by timestamp_ms and sort ascending
                seen_ts: set[int | None] = set()
                unique_locations: list[dict[str, Any]] = []
                for loc in locations:
                    ts = loc.get("timestamp_ms")
                    if ts in seen_ts and ts is not None:
                        continue
                    seen_ts.add(ts)
                    unique_locations.append(loc)

                unique_locations.sort(
                    key=lambda x: x.get("timestamp_ms") or 0
                )
                tag_data["locations"] = unique_locations

            except Exception:
                _LOGGER.exception(
                    "Failed to get location history for %s", device_id
                )

            result[device_id] = tag_data

        return result

    def _parse_geo(
        self, geo: dict[str, Any], key_pairs: list[dict]
    ) -> dict[str, Any] | None:
        """Parse a single geolocation entry into a standard dict."""
        lat_raw = geo.get("latitude", "0")
        lon_raw = geo.get("longitude", "0")

        try:
            lat, lon = float(lat_raw), float(lon_raw)
        except (ValueError, TypeError):
            lat, lon = self._decrypt_location(
                str(lat_raw), str(lon_raw), key_pairs
            )

        if lat == 0.0 and lon == 0.0:
            return None

        timestamp_ms = geo.get("lastUpdateTime")
        if isinstance(timestamp_ms, str):
            try:
                timestamp_ms = int(timestamp_ms)
            except (ValueError, TypeError):
                timestamp_ms = None

        return {
            "latitude": lat,
            "longitude": lon,
            "accuracy": self._safe_float(geo.get("accuracy")),
            "battery_level": geo.get("battery") or geo.get("batteryLevel"),
            "timestamp_ms": timestamp_ms,
        }

    async def get_all_tag_data_with_history(
        self,
        last_poll_timestamps: dict[str, int],
    ) -> dict[str, dict[str, Any]]:
        """Fetch all tracker devices with location history since last poll.

        Returns dict keyed by device_id with:
          - name, model_name, device_id
          - locations: list of {latitude, longitude, accuracy, battery_level, timestamp_ms}
                       ordered ascending by time
        """
        trackers = await self.get_tracker_list()
        result: dict[str, dict[str, Any]] = {}

        for tracker in trackers:
            device_id = tracker.get("stDid") or tracker.get("deviceId", "")
            if not device_id:
                continue

            name = tracker.get("stDevName", device_id)
            model_name = tracker.get("modelName", "SmartTag")

            tag_data: dict[str, Any] = {
                "name": name,
                "model_name": model_name,
                "device_id": device_id,
                "locations": [],
            }

            try:
                # Get current location (for E2E key pairs)
                loc_result = await self.get_location(device_id)
                key_pairs = loc_result.get("keyPairs", [])

                # Determine start_time for history fetch
                start_time = last_poll_timestamps.get(device_id)

                # Fetch history since last poll
                history_geos = await self.get_location_history(
                    device_id, start_time=start_time
                )

                locations: list[dict[str, Any]] = []
                for geo in history_geos:
                    parsed = self._parse_geo(geo, key_pairs)
                    if parsed:
                        locations.append(parsed)

                # Also include current location from the geolocation endpoint
                # (may be newer than last history entry)
                items = loc_result.get("items", [])
                for item in items:
                    if item.get("deviceId") != device_id:
                        continue
                    geos = item.get("geolocations") or item.get("geoLocations", [])
                    for geo in geos:
                        parsed = self._parse_geo(geo, key_pairs)
                        if parsed:
                            locations.append(parsed)

                # Deduplicate by timestamp_ms and sort ascending
                seen_ts: set[int | None] = set()
                unique_locations: list[dict[str, Any]] = []
                for loc in locations:
                    ts = loc.get("timestamp_ms")
                    if ts in seen_ts and ts is not None:
                        continue
                    seen_ts.add(ts)
                    unique_locations.append(loc)

                unique_locations.sort(
                    key=lambda x: x.get("timestamp_ms") or 0
                )
                tag_data["locations"] = unique_locations

            except Exception:
                _LOGGER.exception(
                    "Failed to get location history for %s", device_id
                )

            result[device_id] = tag_data

        return result
