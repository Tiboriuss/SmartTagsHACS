"""Sensor platform for Samsung SmartTags — last seen timestamp."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import SmartTagsCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Samsung SmartTag last-seen sensors."""
    runtime_data = entry.runtime_data
    coordinator: SmartTagsCoordinator = runtime_data.coordinator

    entities: list[SmartTagLastSeenSensor] = []
    if coordinator.data:
        for device_id in coordinator.data:
            entities.append(
                SmartTagLastSeenSensor(
                    coordinator=coordinator,
                    device_id=device_id,
                    entry_id=entry.entry_id,
                )
            )

    async_add_entities(entities)

    known_device_ids = set(coordinator.data.keys()) if coordinator.data else set()

    @callback
    def _async_check_new_tags() -> None:
        nonlocal known_device_ids
        if not coordinator.data:
            return
        new_ids = set(coordinator.data.keys()) - known_device_ids
        if new_ids:
            new_entities = [
                SmartTagLastSeenSensor(
                    coordinator=coordinator,
                    device_id=device_id,
                    entry_id=entry.entry_id,
                )
                for device_id in new_ids
            ]
            async_add_entities(new_entities)
            known_device_ids |= new_ids

    entry.async_on_unload(coordinator.async_add_listener(_async_check_new_tags))


class SmartTagLastSeenSensor(CoordinatorEntity[SmartTagsCoordinator], SensorEntity):
    """Sensor showing the last time Samsung reported a tag location."""

    _attr_has_entity_name = True
    _attr_name = "Last seen"
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(
        self,
        coordinator: SmartTagsCoordinator,
        device_id: str,
        entry_id: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._device_id = device_id
        self._attr_unique_id = f"{entry_id}_{device_id}_last_seen"

        tag_data = self._tag_data
        name = tag_data.get("name", device_id) if tag_data else device_id
        model = tag_data.get("model_name", "SmartTag") if tag_data else "SmartTag"

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_id)},
            name=name,
            manufacturer="Samsung",
            model=model,
        )

    @property
    def _tag_data(self) -> dict[str, Any] | None:
        """Get current tag data from coordinator."""
        if self.coordinator.data:
            return self.coordinator.data.get(self._device_id)
        return None

    @property
    def native_value(self) -> datetime | None:
        """Return the last-seen timestamp as a datetime."""
        data = self._tag_data
        if not data:
            return None
        locations = data.get("locations", [])
        if not locations:
            return None
        last_ts = locations[-1].get("timestamp_ms")
        if last_ts is None:
            return None
        try:
            return datetime.fromtimestamp(int(last_ts) / 1000, tz=timezone.utc)
        except (ValueError, TypeError, OSError):
            return None
