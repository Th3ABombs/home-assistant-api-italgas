"""Test end-to-end contro il portale reale (usa credentials.json, saltato se assente)."""
import json
from datetime import timedelta
from pathlib import Path

import asyncio
import socket

import aiohttp
import aiohttp.abc
import pytest_socket
from pytest_homeassistant_custom_component import plugins as ha_plugins
import pytest
from unittest.mock import patch
from homeassistant import config_entries
from homeassistant.components.recorder.statistics import statistics_during_period
from homeassistant.components.recorder import get_instance
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.components.recorder.common import (
    async_wait_recording_done,
)

from custom_components.italgas.const import DOMAIN

CREDS = Path(__file__).parent.parent / "credentials.json"
pytestmark = pytest.mark.skipif(not CREDS.exists(), reason="credentials.json assente")


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(recorder_mock, enable_custom_integrations):
    """Il recorder deve partire prima di hass."""
    yield


@pytest.fixture
def expected_lingering_timers():
    return True


class _RealResolver(aiohttp.abc.AbstractResolver):
    """Risolve con il getaddrinfo originale (il plugin di test blocca il DNS)."""

    async def resolve(self, host, port=0, family=socket.AF_INET):
        infos = await asyncio.get_running_loop().run_in_executor(
            None, lambda: ha_plugins._real_getaddrinfo(host, port, family, socket.SOCK_STREAM)
        )
        # consente la connessione solo verso gli IP del portale appena risolti
        pytest_socket.socket_allow_hosts(["127.0.0.1"] + [i[4][0] for i in infos])
        return [
            {"hostname": host, "host": i[4][0], "port": i[4][1], "family": i[0],
             "proto": i[2], "flags": socket.AI_NUMERICHOST}
            for i in infos
        ]

    async def close(self):
        pass


@pytest.fixture
async def real_session():
    """Nei test il resolver DNS di HA è legato a un altro loop: sessione semplice."""
    session = aiohttp.ClientSession(
        connector=aiohttp.TCPConnector(resolver=_RealResolver())
    )
    with (
        patch("custom_components.italgas.config_flow.async_create_clientsession", return_value=session),
        patch("custom_components.italgas.async_create_clientsession", return_value=session),
    ):
        yield
    await session.close()


async def test_setup_and_import(recorder_mock, hass, socket_enabled, real_session):
    creds = json.loads(CREDS.read_text())
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"username": creds["username"], "password": creds["password"], "pdr": ""},
    )
    assert result["type"] == "create_entry", result
    pdr = result["data"]["pdr"]
    assert len(pdr) == 14
    await hass.async_block_till_done()
    await async_wait_recording_done(hass)

    states = {s.entity_id: s.state for s in hass.states.async_all("sensor")}
    print("\nSENSORI:", json.dumps(states, indent=1))
    assert any(v not in ("unknown", "unavailable") for v in states.values())

    stat_id = f"{DOMAIN}:gas_{pdr}"
    start = dt_util.utcnow() - timedelta(days=3650)

    def _stats():
        return statistics_during_period(
            hass, start, None, {stat_id}, "month", None, {"change", "sum", "state"}
        ).get(stat_id, [])

    rows = await get_instance(hass).async_add_executor_job(_stats)
    print(f"STATISTICHE MENSILI ({len(rows)}):")
    for r in rows:
        print(" ", dt_util.as_local(dt_util.utc_from_timestamp(r["start"])).date(),
              "state", r["state"], "sum", r["sum"], "change", r["change"])
    assert len(rows) >= 12
    assert all(r["change"] >= 0 for r in rows)

    # secondo aggiornamento: nessun duplicato, somma invariata
    coordinator = hass.data[DOMAIN][result["result"].entry_id]
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    await async_wait_recording_done(hass)
    rows2 = await get_instance(hass).async_add_executor_job(_stats)
    assert len(rows2) == len(rows)
    assert rows2[-1]["sum"] == rows[-1]["sum"]
