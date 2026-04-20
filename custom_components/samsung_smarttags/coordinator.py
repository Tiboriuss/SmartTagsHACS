"""DataUpdateCoordinator for Samsung SmartTags."""

from __future__ import annotations

import logging
import time
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import CONF_SCAN_INTERVAL, CONF_TOKENS, DEFAULT_SCAN_INTERVAL, DOMAIN
from .samsung_auth import SamsungAuth, SamsungAuthError
from .samsung_client import SmartTagsAuthError, SmartTagsClient, SmartTagsClientError

_LOGGER = logging.getLogger(__name__)

# On first run, fetch the last hour of history
_INITIAL_HISTORY_MS = 60 * 60 * 1000


class SamsungSmartTagsData:
    """Runtime data for Samsung SmartTags integration."""

    def __init__(
        self,
        auth: SamsungAuth,
        client: SmartTagsClient,
        coordinator: SmartTagsCoordinator,
    ) -> None:
        self.auth = auth
        self.client = client
        self.coordinator = coordinator


class SmartTagsCoordinator(DataUpdateCoordinator[dict[str, dict[str, Any]]]):
    """Coordinator to fetch Smart Tag locations with history."""

    def __init__(
        self,
        hass: HomeAssistant,
        auth: SamsungAuth,
        client: SmartTagsClient,
        entry: ConfigEntry,
    ) -> None:
        scan_interval = entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(minutes=scan_interval),
        )
        self._auth = auth
        self._client = client
        self._entry = entry
        # Track last poll timestamp per device (ms epoch) for incremental history
        self._last_poll_timestamps: dict[str, int] = {}

    async def _async_update_data(self) -> dict[str, dict[str, Any]]:
        """Fetch location history from Samsung SmartThings API."""
        # On first poll, seed timestamps to 1 hour ago
        if not self._last_poll_timestamps:
            now_ms = int(time.time() * 1000)
            # We don't know device IDs yet; pass empty dict,
            # client will fetch all history if no start_time for a device
            seed_ts = now_ms - _INITIAL_HISTORY_MS
            # Will be populated after first successful fetch
            _LOGGER.debug(
                "First poll: will fetch history from %s ms ago", _INITIAL_HISTORY_MS
            )
            # Temporarily set a default start time
            default_start = seed_ts
        else:
            default_start = None

        # Build the start times dict
        poll_timestamps = dict(self._last_poll_timestamps)
        if default_start is not None:
            # For devices we haven't seen yet, use the seeded start
            poll_timestamps = _DefaultDict(poll_timestamps, default_start)

        try:
            data = await self._fetch_data(poll_timestamps)
        except SmartTagsAuthError:
            data = await self._refresh_and_retry(poll_timestamps)

        # Update last poll timestamps from the fetched data
        for device_id, tag_data in data.items():
            locations = tag_data.get("locations", [])
            if locations:
                last_ts = locations[-1].get("timestamp_ms")
                if last_ts is not None:
                    # +1ms to avoid re-fetching the same point
                    self._last_poll_timestamps[device_id] = last_ts + 1

        return data

    async def _fetch_data(
        self, poll_timestamps: dict[str, int]
    ) -> dict[str, dict[str, Any]]:
        """Fetch data, raising on error."""
        try:
            return await self._client.get_all_tag_data_with_history(poll_timestamps)
        except SmartTagsClientError as err:
            raise UpdateFailed(f"Error fetching tag data: {err}") from err

    async def _refresh_and_retry(
        self, poll_timestamps: dict[str, int]
    ) -> dict[str, dict[str, Any]]:
        """Refresh token and retry fetch."""
        try:
            tokens = self._entry.data[CONF_TOKENS]
            updated_tokens = await self._auth.refresh_token(tokens, "smartthings")
            new_data = {**self._entry.data, CONF_TOKENS: updated_tokens}
            self.hass.config_entries.async_update_entry(
                self._entry, data=new_data
            )
            self._client.update_tokens(updated_tokens)
            return await self._fetch_data(poll_timestamps)
        except SamsungAuthError as err:
            raise ConfigEntryAuthFailed(
                "Samsung authentication failed. Please re-authenticate."
            ) from err
        except SmartTagsClientError as err:
            raise UpdateFailed(f"Error fetching tag data: {err}") from err


class _DefaultDict(dict):
    """Dict that returns a default value for missing keys."""

    def __init__(self, base: dict, default: int) -> None:
        super().__init__(base)
        self._default = default

    def get(self, key: str, default: int | None = None) -> int:  # type: ignore[override]
        """Return value for key, or the seeded default."""
        if key in self:
            return super().__getitem__(key)
        return self._default
