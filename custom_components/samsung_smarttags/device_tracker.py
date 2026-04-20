"""Device tracker platform for Samsung SmartTags."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.device_tracker import SourceType, TrackerEntity
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
    """Set up Samsung SmartTag device trackers."""
    runtime_data = entry.runtime_data
    coordinator: SmartTagsCoordinator = runtime_data.coordinator

    # Create entities for each tag found in the initial data
    entities: list[SmartTagTrackerEntity] = []
    if coordinator.data:
        for device_id, tag_data in coordinator.data.items():
            entities.append(
                SmartTagTrackerEntity(
                    coordinator=coordinator,
                    device_id=device_id,
                    entry_id=entry.entry_id,
                )
            )

    async_add_entities(entities)

    # Track new tags that appear in future updates
    known_device_ids = set(coordinator.data.keys()) if coordinator.data else set()

    @callback
    def _async_check_new_tags() -> None:
        nonlocal known_device_ids
        if not coordinator.data:
            return
        new_ids = set(coordinator.data.keys()) - known_device_ids
        if new_ids:
            new_entities = [
                SmartTagTrackerEntity(
                    coordinator=coordinator,
                    device_id=device_id,
                    entry_id=entry.entry_id,
                )
                for device_id in new_ids
            ]
            async_add_entities(new_entities)
            known_device_ids |= new_ids

    entry.async_on_unload(coordinator.async_add_listener(_async_check_new_tags))


class SmartTagTrackerEntity(CoordinatorEntity[SmartTagsCoordinator], TrackerEntity):
    """Represent a Samsung SmartTag as a device tracker."""

    _attr_has_entity_name = True
    _attr_name = None

    def __init__(
        self,
        coordinator: SmartTagsCoordinator,
        device_id: str,
        entry_id: str,
    ) -> None:
        """Initialize the tracker entity."""
        super().__init__(coordinator)
        self._device_id = device_id
        self._attr_unique_id = f"{entry_id}_{device_id}"

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
    def latitude(self) -> float | None:
        """Return latitude value of the device."""
        data = self._tag_data
        return data.get("latitude") if data else None

    @property
    def longitude(self) -> float | None:
        """Return longitude value of the device."""
        data = self._tag_data
        return data.get("longitude") if data else None

    @property
    def location_accuracy(self) -> int:
        """Return the location accuracy of the device."""
        data = self._tag_data
        if data and data.get("accuracy") is not None:
            return int(data["accuracy"])
        return 0

    @property
    def battery_level(self) -> int | None:
        """Return the battery level of the device."""
        data = self._tag_data
        if data and data.get("battery_level") is not None:
            try:
                return int(data["battery_level"])
            except (ValueError, TypeError):
                return None
        return None

    @property
    def source_type(self) -> SourceType:
        """Return the source type of the device."""
        return SourceType.GPS
