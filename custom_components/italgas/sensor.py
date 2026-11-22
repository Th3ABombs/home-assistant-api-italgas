"""Sensori Italgas."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfVolume
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import Reading, period_consumption
from .const import CONF_PDR, DOMAIN
from .coordinator import ItalgasCoordinator


@dataclass(frozen=True, kw_only=True)
class ItalgasSensorDescription(SensorEntityDescription):
    value_fn: Callable[[list[Reading]], Any]
    attrs_fn: Callable[[list[Reading]], dict[str, Any]] | None = None


def _last_consumption(r: list[Reading]):
    c = period_consumption(r)
    return c[-1][1] if c else None


SENSORS: tuple[ItalgasSensorDescription, ...] = (
    ItalgasSensorDescription(
        key="meter_reading",
        translation_key="meter_reading",
        device_class=SensorDeviceClass.GAS,
        # niente state_class: lo storico per la dashboard Energia è la statistica
        # esterna italgas:gas_<PdR>; con state_class HA creerebbe un doppione
        # (statistiche ogni 5 minuti sempre a 0)
        native_unit_of_measurement=UnitOfVolume.CUBIC_METERS,
        value_fn=lambda r: r[-1].value,
        attrs_fn=lambda r: {
            "data_lettura": r[-1].date.isoformat(),
            "tipo_lettura": r[-1].kind,
        },
    ),
    ItalgasSensorDescription(
        key="last_reading_date",
        translation_key="last_reading_date",
        device_class=SensorDeviceClass.DATE,
        value_fn=lambda r: r[-1].date,
    ),
    ItalgasSensorDescription(
        key="last_period_consumption",
        translation_key="last_period_consumption",
        device_class=SensorDeviceClass.GAS,
        native_unit_of_measurement=UnitOfVolume.CUBIC_METERS,
        value_fn=_last_consumption,
        attrs_fn=lambda r: {
            "storico": [
                {"data": d.isoformat(), "consumo_m3": v}
                for d, v in period_consumption(r)[-24:]
            ]
        },
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: ItalgasCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(ItalgasSensor(coordinator, entry, d) for d in SENSORS)


class ItalgasSensor(CoordinatorEntity[ItalgasCoordinator], SensorEntity):
    _attr_has_entity_name = True
    entity_description: ItalgasSensorDescription

    def __init__(self, coordinator, entry: ConfigEntry, description) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        pdr = entry.data.get(CONF_PDR) or entry.entry_id
        self._attr_unique_id = f"{pdr}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, pdr)},
            name=f"Contatore gas {pdr}",
            manufacturer="Italgas",
        )

    @property
    def native_value(self):
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self):
        fn = self.entity_description.attrs_fn
        return fn(self.coordinator.data) if fn else None
