"""DataUpdateCoordinator per Italgas + importazione statistiche storiche."""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.models import (
    StatisticData,
    StatisticMeanType,
    StatisticMetaData,
)
from homeassistant.components.recorder.statistics import (
    async_add_external_statistics,
    get_last_statistics,
)
from homeassistant.const import UnitOfVolume
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util
from homeassistant.util.unit_conversion import VolumeConverter

from .api import ItalgasAuthError, ItalgasClient, ItalgasError, Reading
from .const import DEFAULT_SCAN_INTERVAL, DOMAIN, HISTORY_YEARS, MIN_FETCH_INTERVAL

STORAGE_VERSION = 1

_LOGGER = logging.getLogger(__name__)


def statistic_id_for(pdr: str) -> str:
    return f"{DOMAIN}:gas_{pdr}"


def reading_start(d: date) -> datetime:
    """Istante (UTC) a cui associare una lettura: mezzanotte locale del giorno."""
    return dt_util.as_utc(
        datetime(d.year, d.month, d.day, tzinfo=dt_util.get_default_time_zone())
    )


def build_statistics(
    readings: list[Reading],
    last_start: datetime | None,
    last_state: float | None,
    last_sum: float | None,
) -> list[StatisticData]:
    """Statistiche da aggiungere dopo l'ultima già presente.

    - state = valore del contatore
    - sum   = consumo cumulativo dall'inizio dello storico importato
    Il cruscotto Energia usa le differenze di `sum`, quindi la prima lettura
    importata vale 0 e ogni lettura successiva aggiunge il consumo del periodo.
    """
    stats: list[StatisticData] = []
    prev_state, total = last_state, last_sum or 0.0
    for r in readings:
        start = reading_start(r.date)
        if last_start is not None and start <= last_start:
            continue
        if prev_state is not None:
            delta = r.value - prev_state
            if delta < 0:
                # contatore sostituito: il nuovo riparte da 0, quindi il suo
                # valore è il consumo dall'installazione
                _LOGGER.info(
                    "Lettura %s (%s m³) inferiore alla precedente (%s m³): "
                    "considero un nuovo contatore",
                    r.date, r.value, prev_state,
                )
                delta = r.value
            total += delta
        stats.append(StatisticData(start=start, state=r.value, sum=round(total, 3)))
        prev_state = r.value
    return stats


def needs_fetch(
    latest: date | None,
    last_fetch: datetime | None,
    now: datetime,
    today: date,
) -> bool:
    """True se conviene contattare il portale.

    Le letture sono mensili (datate a fine mese): se abbiamo già quella di fine
    del mese precedente non serve chiedere nulla fino al mese prossimo. Quando
    una lettura è attesa, al massimo un accesso ogni MIN_FETCH_INTERVAL.
    """
    if latest is None or last_fetch is None:
        return True
    end_prev_month = today.replace(day=1) - timedelta(days=1)
    if latest >= end_prev_month:
        return False
    return now - last_fetch >= MIN_FETCH_INTERVAL


def reading_to_dict(r: Reading) -> dict:
    return {"date": r.date.isoformat(), "value": r.value, "kind": r.kind, "meter": r.meter}


def reading_from_dict(d: dict) -> Reading:
    return Reading(
        date=date.fromisoformat(d["date"]),
        value=d["value"],
        kind=d.get("kind"),
        meter=d.get("meter"),
    )


class ItalgasCoordinator(DataUpdateCoordinator[list[Reading]]):
    def __init__(self, hass: HomeAssistant, client: ItalgasClient, pdr: str) -> None:
        super().__init__(
            hass, _LOGGER, name=DOMAIN, update_interval=DEFAULT_SCAN_INTERVAL
        )
        self.client = client
        self.pdr = pdr
        self.statistic_id = statistic_id_for(pdr)
        self._store: Store[dict] = Store(hass, STORAGE_VERSION, f"{DOMAIN}.{pdr}")
        self._cache: list[Reading] | None = None
        self._last_fetch: datetime | None = None

    async def _load_cache(self) -> None:
        if self._cache is not None:
            return
        data = await self._store.async_load() or {}
        self._cache = [reading_from_dict(r) for r in data.get("readings", [])]
        if ts := data.get("last_fetch"):
            self._last_fetch = dt_util.parse_datetime(ts)

    async def _save_cache(self, readings: list[Reading]) -> None:
        self._cache, self._last_fetch = readings, dt_util.utcnow()
        await self._store.async_save(
            {
                "last_fetch": self._last_fetch.isoformat(),
                "readings": [reading_to_dict(r) for r in readings],
            }
        )

    async def _async_update_data(self) -> list[Reading]:
        await self._load_cache()
        last = await get_instance(self.hass).async_add_executor_job(
            get_last_statistics, self.hass, 1, self.statistic_id, True, {"state", "sum"}
        )
        last_row = (last.get(self.statistic_id) or [None])[0]

        latest = self._cache[-1].date if self._cache else None
        if last_row is not None and not needs_fetch(
            latest, self._last_fetch, dt_util.utcnow(), dt_util.now().date()
        ):
            _LOGGER.debug(
                "Italgas: nessuna richiesta al portale (ultima lettura %s, ultimo accesso %s)",
                latest, self._last_fetch,
            )
            return self._cache

        # primo avvio: tutto lo storico disponibile; poi solo gli ultimi 12 mesi
        start = None
        if last_row is None:
            start = date.today() - timedelta(days=365 * HISTORY_YEARS)

        _LOGGER.info("Italgas: richiesta letture al portale")
        try:
            readings = await self.client.get_readings(start=start)
        except ItalgasAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except ItalgasError as err:
            raise UpdateFailed(f"Errore Italgas: {err}") from err
        except Exception as err:  # noqa: BLE001
            raise UpdateFailed(f"Errore imprevisto Italgas: {err}") from err
        if not readings:
            raise UpdateFailed("Nessuna lettura trovata")

        self._import_statistics(readings, last_row)
        await self._save_cache(readings)
        return readings

    def _import_statistics(self, readings: list[Reading], last_row) -> None:
        last_start = (
            dt_util.utc_from_timestamp(last_row["start"]) if last_row else None
        )
        stats = build_statistics(
            readings,
            last_start,
            last_row.get("state") if last_row else None,
            last_row.get("sum") if last_row else None,
        )
        if not stats:
            return
        metadata = StatisticMetaData(
            mean_type=StatisticMeanType.NONE,
            has_sum=True,
            name=f"Gas {self.pdr}",
            source=DOMAIN,
            statistic_id=self.statistic_id,
            unit_class=VolumeConverter.UNIT_CLASS,
            unit_of_measurement=UnitOfVolume.CUBIC_METERS,
        )
        _LOGGER.info(
            "Italgas: importo %d letture in %s (%s → %s)",
            len(stats), self.statistic_id, stats[0]["start"].date(), stats[-1]["start"].date(),
        )
        async_add_external_statistics(self.hass, metadata, stats)
