"""Integrazione Italgas per Home Assistant."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .api import ItalgasClient
from .const import CONF_PDR, DOMAIN
from .coordinator import ItalgasCoordinator

PLATFORMS = [Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    # sessione dedicata: cookie jar separato da quello condiviso di HA
    session = async_create_clientsession(hass)
    pdr = entry.data[CONF_PDR]
    client = ItalgasClient(
        entry.data[CONF_USERNAME], entry.data[CONF_PASSWORD], pdr, session=session
    )
    coordinator = ItalgasCoordinator(hass, client, pdr)
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return ok
