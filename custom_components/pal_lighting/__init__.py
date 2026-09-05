"""The PAL Lighting integration.

One config entry == one PAL 4-switch lighting controller (Hi-Link HF-LPB100
WiFi bridge running the XLink firmware, PAL lighting MCU behind its UART).
Control is fully local over UDP; each command runs the app's proven sequence
(handshake -> probe -> status query -> command) on a fresh socket. See
protocol.py for why the probe and single-socket rules are non-negotiable.

The device exposes no readable switch state (the 0xA4 status frame came back
all zeros), so switch entities are optimistic — exactly like the official app,
which also just remembers what it last sent.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady, HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo

from .const import (
    CONF_ACCESS_KEY,
    CONF_HOST,
    CONF_PASSWORD,
    DEFAULT_ACCESS_KEY,
    DEFAULT_NAME,
    DEFAULT_PASSWORD,
    DOMAIN,
)
from .protocol import PalProtocolError, async_probe_device, async_set_switch

PLATFORMS = ["switch"]

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up PAL Lighting from a config entry."""
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = entry

    # Validate connectivity now so setup failures surface in the UI instead of
    # as silent dead switches later.
    try:
        await async_probe_device(
            entry.data[CONF_HOST],
            entry.data.get(CONF_ACCESS_KEY, DEFAULT_ACCESS_KEY),
        )
    except (PalProtocolError, OSError) as exc:
        raise ConfigEntryNotReady(f"cannot reach PAL controller: {exc}") from exc

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate old config entries forward."""
    if entry.version > 1:
        # downgrade not supported
        return False
    return True


# helpers for entity platforms -----------------------------------------------

def pal_device_info(entry: ConfigEntry) -> DeviceInfo:
    """Shared DeviceInfo — MAC/deviceId come from the validated handshake."""
    return DeviceInfo(
        identifiers={(DOMAIN, entry.data.get("mac", entry.entry_id))},
        name=entry.data.get("name", DEFAULT_NAME),
        manufacturer="szirain / Aiyunxun (PAL Lighting)",
        model="PAL 4-switch remote (Hi-Link HF-LPB100)",
        sw_version=f"XLink MCU v{entry.data.get('mcu_version', '?')}",
    )


async def pal_set_switch(
    hass: HomeAssistant, entry: ConfigEntry, switch_index: int, on: bool
) -> None:
    """Turn a switch on/off, translating protocol errors into HA errors."""
    try:
        await async_set_switch(
            entry.data[CONF_HOST],
            entry.data.get(CONF_ACCESS_KEY, DEFAULT_ACCESS_KEY),
            entry.data.get(CONF_PASSWORD, DEFAULT_PASSWORD),
            switch_index,
            on,
        )
    except PalProtocolError as exc:
        raise HomeAssistantError(f"PAL controller: {exc}") from exc
    except OSError as exc:
        raise HomeAssistantError(
            f"PAL controller network error: {exc}"
        ) from exc