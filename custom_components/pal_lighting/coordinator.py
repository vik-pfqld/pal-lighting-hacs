"""Reachability coordinator for PAL Lighting.

The PAL controller exposes no readable switch state (the 0xA4 status frame came
back all zeros), so this coordinator's only job is availability: it periodically
runs the handshake + probe and, when that stops succeeding, entities flip to
unavailable; when it answers again they come back. Polling interval is
user-configurable at setup (default 20 s; 0 disables the background probe).
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)

from .protocol import DeviceInfo, PalProtocolError, async_probe_device

_LOGGER = logging.getLogger(__name__)


class PalCoordinator(DataUpdateCoordinator):
    """Poll the PAL controller (handshake + probe) to track reachability."""

    def __init__(
        self,
        hass: HomeAssistant,
        host: str,
        access_key: int,
        poll_interval: int,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"pal_lighting {host}",
            update_method=self._async_update,
            update_interval=(
                timedelta(seconds=poll_interval) if poll_interval > 0 else None
            ),
        )
        self.host = host
        self.access_key = access_key
        self.last_device_info: DeviceInfo | None = None

    async def _async_update(self) -> DeviceInfo:
        try:
            info = await async_probe_device(self.host, self.access_key)
        except (PalProtocolError, OSError) as exc:
            raise UpdateFailed(f"PAL controller unreachable: {exc}") from exc
        self.last_device_info = info
        return info