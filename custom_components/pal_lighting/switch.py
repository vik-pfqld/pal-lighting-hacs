"""Switch entities for PAL Lighting — the 4 buttons of the app's remote."""

from __future__ import annotations

from homeassistant.components.switch import SwitchDeviceClass, SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import pal_device_info, pal_set_switch
from .const import SWITCH_COUNT
from .coordinator import PalCoordinator

_SWITCH_NAMES = {
    1: "Switch 1",
    2: "Switch 2",
    3: "Switch 3",
    4: "Switch 4",
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the four PAL switches from a config entry."""
    coordinator: PalCoordinator = hass.data[entry.domain][entry.entry_id]
    async_add_entities(
        PalSwitch(coordinator, entry, index) for index in range(1, SWITCH_COUNT + 1)
    )


class PalSwitch(CoordinatorEntity, RestoreEntity, SwitchEntity):
    """One physical switch on the PAL 4-button remote.

    The device reports no readable state, so this entity is optimistic: it
    reflects the last command we sent (the official app behaves the same).
    Availability comes from the coordinator's reachability probe — if the
    controller stops answering the poll, the entity flips to unavailable and
    back when it answers again.
    """

    _attr_should_poll = False
    _attr_device_class = SwitchDeviceClass.SWITCH
    _attr_assumed_state = True
    _attr_has_entity_name = True

    def __init__(
        self, coordinator: PalCoordinator, entry: ConfigEntry, index: int
    ) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._index = index
        self._attr_unique_id = f"pal_{entry.data.get('mac', entry.entry_id)}_{index}"
        self._attr_name = _SWITCH_NAMES[index]
        self._attr_is_on = None  # unknown until restored or first command

    @property
    def device_info(self):
        return pal_device_info(self._entry)

    async def async_added_to_hass(self) -> None:
        """Restore the last commanded state across restarts.

        Only 'on'/'off' are meaningful — restored 'unavailable'/'unknown' are
        transport artifacts from the previous shutdown, not switch state.
        """
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is not None and last_state.state in ("on", "off"):
            self._attr_is_on = last_state.state == "on"

    async def async_turn_on(self, **kwargs) -> None:
        await pal_set_switch(self.coordinator.hass, self._entry, self._index, True)
        self._attr_is_on = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        await pal_set_switch(self.coordinator.hass, self._entry, self._index, False)
        self._attr_is_on = False
        self.async_write_ha_state()