"""Device tracker platform for Samsung SmartTags."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
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

    entities: list[SmartTagTrackerEntity] = []
    if coordinator.data:
        for device_id in coordinator.data:
            entities.append(
                SmartTagTrackerEntity(
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

        # Current location state (updated during replay)
        self._current_lat: float | None = None
        self._current_lon: float | None = None
        self._current_accuracy: float | None = None
        self._current_battery: int | None = None
        self._samsung_timestamp: str | None = None

        tag_data = self._tag_data
        name = tag_data.get("name", device_id) if tag_data else device_id
        model = tag_data.get("model_name", "SmartTag") if tag_data else "SmartTag"

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_id)},
            name=name,
            manufacturer="Samsung",
            model=model,
        )

        # Set initial state from the latest location
        self._apply_latest_location()

    @property
    def _tag_data(self) -> dict[str, Any] | None:
        """Get current tag data from coordinator."""
        if self.coordinator.data:
            return self.coordinator.data.get(self._device_id)
        return None

    def _apply_latest_location(self) -> None:
        """Apply the most recent location from coordinator data."""
        data = self._tag_data
        if not data:
            return
        locations = data.get("locations", [])
        if locations:
            loc = locations[-1]
            self._current_lat = loc.get("latitude")
            self._current_lon = loc.get("longitude")
            self._current_accuracy = loc.get("accuracy")
            battery = loc.get("battery_level")
            if battery is not None:
                try:
                    self._current_battery = int(battery)
                except (ValueError, TypeError):
                    pass
            ts_ms = loc.get("timestamp_ms")
            if ts_ms is not None:
                self._samsung_timestamp = (
                    datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).isoformat()
                )

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator.

        Replay all intermediate locations as individual state writes,
        so that HA Recorder captures each point.
        """
        data = self._tag_data
        if not data:
            super()._handle_coordinator_update()
            return

        locations = data.get("locations", [])
        if not locations:
            super()._handle_coordinator_update()
            return

        # Replay each intermediate location as a state update
        for loc in locations:
            lat = loc.get("latitude")
            lon = loc.get("longitude")
            if lat is None or lon is None:
                continue

            self._current_lat = lat
            self._current_lon = lon
            self._current_accuracy = loc.get("accuracy")

            battery = loc.get("battery_level")
            if battery is not None:
                try:
                    self._current_battery = int(battery)
                except (ValueError, TypeError):
                    pass

            ts_ms = loc.get("timestamp_ms")
            if ts_ms is not None:
                self._samsung_timestamp = (
                    datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).isoformat()
                )

            # Write this intermediate state to HA (Recorder captures it)
            self.async_write_ha_state()

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes including Samsung timestamp."""
        attrs: dict[str, Any] = {}
        if self._samsung_timestamp:
            attrs["samsung_timestamp"] = self._samsung_timestamp
        if self._current_accuracy is not None:
            attrs["samsung_accuracy"] = self._current_accuracy
        if self._current_battery is not None:
            attrs["samsung_battery"] = self._current_battery
        return attrs

    @property
    def latitude(self) -> float | None:
        """Return latitude value of the device."""
        return self._current_lat

    @property
    def longitude(self) -> float | None:
        """Return longitude value of the device."""
        return self._current_lon

    @property
    def location_accuracy(self) -> int:
        """Return the location accuracy of the device."""
        if self._current_accuracy is not None:
            return int(self._current_accuracy)
        return 0

    @property
    def battery_level(self) -> int | None:
        """Return the battery level of the device."""
        return self._current_battery

    @property
    def source_type(self) -> SourceType:
        """Return the source type of the device."""
        return SourceType.GPS
