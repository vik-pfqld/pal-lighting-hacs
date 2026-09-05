"""Switch entities for PAL Lighting — the 4 buttons of the app's remote."""

from __future__ import annotations

from homeassistant.components.switch import SwitchDeviceClass, SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import pal_device_info, pal_set_switch
from .const import SWITCH_COUNT

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
    async_add_entities(
        PalSwitch(hass, entry, index) for index in range(1, SWITCH_COUNT + 1)
    )


class PalSwitch(SwitchEntity):
    """One physical switch on the PAL 4-button remote.

    The device reports no readable state, so this entity is optimistic: it
    reflects the last command we sent (the official app behaves the same).
    """

    _attr_should_poll = False
    _attr_device_class = SwitchDeviceClass.SWITCH
    _attr_assumed_state = True
    _attr_has_entity_name = True

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, index: int
    ) -> None:
        self._hass = hass
        self._entry = entry
        self._index = index
        self._attr_unique_id = f"pal_{entry.data.get('mac', entry.entry_id)}_{index}"
        self._attr_name = _SWITCH_NAMES[index]
        self._attr_is_on = None  # unknown until first command

    @property
    def device_info(self):
        return pal_device_info(self._entry)

    async def async_turn_on(self, **kwargs) -> None:
        await pal_set_switch(self._hass, self._entry, self._index, True)
        self._attr_is_on = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        await pal_set_switch(self._hass, self._entry, self._index, False)
        self._attr_is_on = False
        self.async_write_ha_state()