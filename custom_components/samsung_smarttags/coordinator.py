"""DataUpdateCoordinator for Samsung SmartTags."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import CONF_TOKENS, DEFAULT_SCAN_INTERVAL, DOMAIN
from .samsung_auth import SamsungAuth, SamsungAuthError
from .samsung_client import SmartTagsAuthError, SmartTagsClient, SmartTagsClientError

_LOGGER = logging.getLogger(__name__)


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
    """Coordinator to fetch Smart Tag locations."""

    def __init__(
        self,
        hass: HomeAssistant,
        auth: SamsungAuth,
        client: SmartTagsClient,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(minutes=DEFAULT_SCAN_INTERVAL),
        )
        self._auth = auth
        self._client = client
        self._entry = entry

    async def _async_update_data(self) -> dict[str, dict[str, Any]]:
        """Fetch data from Samsung SmartThings API."""
        try:
            return await self._client.get_all_tag_data()
        except SmartTagsAuthError:
            # Token expired — try to refresh
            try:
                tokens = self._entry.data[CONF_TOKENS]
                updated_tokens = await self._auth.refresh_token(tokens, "smartthings")
                # Persist refreshed tokens
                new_data = {**self._entry.data, CONF_TOKENS: updated_tokens}
                self.hass.config_entries.async_update_entry(
                    self._entry, data=new_data
                )
                self._client.update_tokens(updated_tokens)
                # Retry after refresh
                return await self._client.get_all_tag_data()
            except SamsungAuthError as err:
                raise ConfigEntryAuthFailed(
                    "Samsung authentication failed. Please re-authenticate."
                ) from err
            except SmartTagsClientError as err:
                raise UpdateFailed(f"Error fetching tag data: {err}") from err
        except SmartTagsClientError as err:
            raise UpdateFailed(f"Error fetching tag data: {err}") from err
