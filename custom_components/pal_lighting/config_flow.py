"""Config flow for PAL Lighting."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult

from .const import (
    CONF_ACCESS_KEY,
    CONF_HOST,
    CONF_PASSWORD,
    DEFAULT_ACCESS_KEY,
    DEFAULT_NAME,
    DEFAULT_PASSWORD,
    DOMAIN,
)
from .protocol import PalProtocolError, async_probe_device

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Optional(CONF_ACCESS_KEY, default=DEFAULT_ACCESS_KEY): vol.All(
            vol.Coerce(int), vol.Range(min=0, max=0xFFFFFFFF)
        ),
        vol.Optional(CONF_PASSWORD, default=DEFAULT_PASSWORD): vol.All(
            vol.Coerce(int), vol.Range(min=0, max=255)
        ),
    }
)


class PalLightingConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for PAL Lighting."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                info = await async_probe_device(
                    user_input[CONF_HOST], user_input[CONF_ACCESS_KEY]
                )
            except PalProtocolError:
                errors["base"] = "cannot_connect"
            except OSError:
                errors["base"] = "cannot_connect"
            else:
                # remember the handshake-derived identity for the device registry
                user_input["mac"] = info.mac
                user_input["device_id"] = info.device_id
                user_input["mcu_version"] = info.mcu_version
                await self.async_set_unique_id(f"pal_{info.mac}")
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"{DEFAULT_NAME} ({info.mac[-5:]})",
                    data=user_input,
                )

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
            description_placeholders={
                "host_hint": "e.g. 192.168.20.170 (find it in your router's DHCP table)"
            },
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> PalLightingOptionsFlow:
        return PalLightingOptionsFlow()


class PalLightingOptionsFlow(config_entries.OptionsFlow):
    """Options — re-ask the advanced fields only."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current = self.config_entry.data
        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_ACCESS_KEY,
                    default=current.get(CONF_ACCESS_KEY, DEFAULT_ACCESS_KEY),
                ): vol.All(vol.Coerce(int), vol.Range(min=0, max=0xFFFFFFFF)),
                vol.Optional(
                    CONF_PASSWORD,
                    default=current.get(CONF_PASSWORD, DEFAULT_PASSWORD),
                ): vol.All(vol.Coerce(int), vol.Range(min=0, max=255)),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)