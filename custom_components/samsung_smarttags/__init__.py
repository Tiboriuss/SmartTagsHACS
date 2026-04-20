"""Samsung SmartTags integration for Home Assistant."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import CONF_COUNTRY_CODE, CONF_E2E_PIN, CONF_LANGUAGE, CONF_TOKENS
from .coordinator import SamsungSmartTagsData, SmartTagsCoordinator
from .samsung_auth import SamsungAuth
from .samsung_client import SmartTagsClient

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.DEVICE_TRACKER]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Samsung SmartTags from a config entry."""
    session = async_get_clientsession(hass)

    tokens = entry.data[CONF_TOKENS]
    country_code = entry.data.get(CONF_COUNTRY_CODE, "us")
    language = entry.data.get(CONF_LANGUAGE, "en")
    e2e_pin = entry.data.get(CONF_E2E_PIN, "")

    auth = SamsungAuth(
        session=session,
        country_code=country_code,
        language=language,
    )

    client = SmartTagsClient(
        session=session,
        tokens=tokens,
        e2e_pin=e2e_pin,
    )

    coordinator = SmartTagsCoordinator(
        hass=hass,
        auth=auth,
        client=client,
        entry=entry,
    )

    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = SamsungSmartTagsData(
        auth=auth,
        client=client,
        coordinator=coordinator,
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
