"""Config flow Italgas."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .api import ItalgasAuthError, ItalgasClient, ItalgasError, ItalgasPdrNotFound
from .const import CONF_PDR, DOMAIN

_LOGGER = logging.getLogger(__name__)

SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
        vol.Optional(CONF_PDR, default=""): str,
    }
)


class ItalgasConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            client = ItalgasClient(
                user_input[CONF_USERNAME],
                user_input[CONF_PASSWORD],
                user_input.get(CONF_PDR) or None,
                session=async_create_clientsession(self.hass),
            )
            try:
                supply = await client.get_supply()  # login + verifica PdR
            except ItalgasPdrNotFound:
                errors[CONF_PDR] = "pdr_not_found"
            except ItalgasAuthError:
                errors["base"] = "invalid_auth"
            except ItalgasError as err:
                _LOGGER.warning("Italgas non raggiungibile: %s", err)
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Errore imprevisto durante la configurazione")
                errors["base"] = "unknown"
            else:
                pdr = supply.pdr
                await self.async_set_unique_id(pdr)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"Italgas {pdr}", data={**user_input, CONF_PDR: pdr}
                )
        return self.async_show_form(step_id="user", data_schema=SCHEMA, errors=errors)
