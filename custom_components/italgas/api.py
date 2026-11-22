"""Client per il portale clienti Italgas (scraping, nessuna API ufficiale).

Questo modulo NON importa nulla di Home Assistant, così può essere usato anche
dagli script di test in `scripts/`.

Flusso (verificato a novembre 2026):
  1. GET  login.action                    -> cookie JSESSIONID + token Struts
  2. POST login.action (multipart)        -> sessione autenticata
  3. GET  elencoLettForn.action           -> elenco forniture (PdR, matricola,
                                             link elencoLetture.action?id=<cifrato>)
  4. GET  elencoLetture.action?id=...     -> form "ricercaLetture" (dataDa/dataA)
  5. POST ricercaLetture.action           -> tabella paginata (10 righe/pagina)
  6. GET  link "Esporta CSV" della tabella -> tutte le righe dell'intervallo

Limiti del portale: l'intervallo dataDa/dataA non può superare ~13 mesi
(oltre risponde "Errore di sistema"), quindi lo storico si scarica a finestre.
"""
from __future__ import annotations

import csv
import io
import logging
import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import urljoin

import aiohttp
from bs4 import BeautifulSoup

_LOGGER = logging.getLogger(__name__)

BASE_URL = "https://clienti.italgas.it/clienti/"
LOGIN_URL = urljoin(BASE_URL, "login.action")
SUPPLIES_URL = urljoin(BASE_URL, "elencoLettForn.action")

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"
)

WINDOW_DAYS = 365  # ampiezza di ogni richiesta (il portale accetta max ~13 mesi)
DATE_RE = re.compile(r"\b(\d{2})[/.-](\d{2})[/.-](\d{4})\b")


class ItalgasError(Exception):
    """Errore generico."""


class ItalgasAuthError(ItalgasError):
    """Credenziali errate o sessione non valida."""


class ItalgasPdrNotFound(ItalgasError):
    """Il PdR richiesto non è associato all'account."""


@dataclass
class Supply:
    """Una fornitura associata all'account."""

    pdr: str
    readings_id: str  # id cifrato per elencoLetture.action
    meter: str | None = None  # matricola contatore
    seller: str | None = None
    description: str | None = None


@dataclass
class Reading:
    """Una lettura del contatore."""

    date: date
    value: float  # m³
    kind: str | None = None  # es. "Telelettura", "Autolettura", "Stimata"
    meter: str | None = None
    raw: dict[str, str] = field(default_factory=dict, repr=False)


def _parse_number(text: str) -> float | None:
    """'1.234,56' -> 1234.56 ; '3687.0' -> 3687.0 ; '3687' -> 3687.0."""
    t = re.sub(r"[^\d,.\-]", "", text or "")
    if not re.search(r"\d", t):
        return None
    if "," in t:
        t = t.replace(".", "").replace(",", ".")
    elif t.count(".") > 1:
        t = t.replace(".", "")
    try:
        return float(t)
    except ValueError:
        return None


def _parse_date(text: str) -> date | None:
    m = DATE_RE.search(text or "")
    if not m:
        return None
    d, mo, y = (int(x) for x in m.groups())
    try:
        return date(y, mo, d)
    except ValueError:
        return None


def _form_fields(form) -> dict[str, str]:
    """Valori di default di tutti i campi di un form HTML."""
    data: dict[str, str] = {}
    for inp in form.find_all("input"):
        name = inp.get("name")
        if not name:
            continue
        typ = (inp.get("type") or "text").lower()
        if typ in ("checkbox", "radio") and not inp.has_attr("checked"):
            continue
        if typ in ("submit", "button", "image", "file"):
            continue
        data[name] = inp.get("value", "")
    for sel in form.find_all("select"):
        name = sel.get("name")
        if not name:
            continue
        opt = sel.find("option", selected=True) or sel.find("option")
        data[name] = opt.get("value", opt.get_text(strip=True)) if opt else ""
    return data


def _multipart(fields: dict[str, str]) -> aiohttp.FormData:
    fd = aiohttp.FormData()
    for k, v in fields.items():
        fd.add_field(k, v)
    return fd


def _normalize_pdr(pdr: str | None) -> str | None:
    return re.sub(r"\D", "", pdr) if pdr else None


class ItalgasClient:
    """Client asincrono per il portale Italgas."""

    def __init__(
        self,
        username: str,
        password: str,
        pdr: str | None = None,
        session: aiohttp.ClientSession | None = None,
        debug_dir: str | Path | None = None,
    ) -> None:
        self._username = username
        self._password = password
        self.pdr = _normalize_pdr(pdr)
        self._own_session = session is None
        self._session = session or aiohttp.ClientSession(
            cookie_jar=aiohttp.CookieJar()
        )
        self._debug_dir = Path(debug_dir) if debug_dir else None
        self._logged_in = False

    async def close(self) -> None:
        if self._own_session:
            await self._session.close()

    # ------------------------------------------------------------------ utils
    def _dump(self, name: str, text: str, ext: str = "html") -> None:
        if self._debug_dir:
            self._debug_dir.mkdir(parents=True, exist_ok=True)
            (self._debug_dir / f"{name}.{ext}").write_text(text, encoding="utf-8")

    async def _request(self, method: str, url: str, **kw) -> tuple[str, str]:
        headers = {"User-Agent": USER_AGENT, **kw.pop("headers", {})}
        async with self._session.request(
            method, url, headers=headers, timeout=aiohttp.ClientTimeout(total=60), **kw
        ) as resp:
            resp.raise_for_status()
            return str(resp.url), await resp.text(encoding="utf-8", errors="replace")

    @staticmethod
    def _is_login_page(url: str, html: str) -> bool:
        return "login.action" in url or 'id="headerLogin"' in html

    async def _get_authenticated(self, url: str) -> tuple[str, str]:
        """GET che rifà il login se la sessione è scaduta."""
        if not self._logged_in:
            await self.login()
        final_url, html = await self._request("GET", url)
        if self._is_login_page(final_url, html):
            self._logged_in = False
            await self.login()
            final_url, html = await self._request("GET", url)
            if self._is_login_page(final_url, html):
                raise ItalgasAuthError("Sessione non valida dopo il login")
        return final_url, html

    # ------------------------------------------------------------------ login
    async def login(self) -> None:
        url, html = await self._request("GET", LOGIN_URL)
        self._dump("01_login_get", html)
        form = BeautifulSoup(html, "html.parser").find("form", id="headerLogin")
        if form is None:
            if "logout.action" in html:  # sessione già autenticata
                self._logged_in = True
                return
            raise ItalgasError("Form di login non trovato (il sito è cambiato?)")

        fields = _form_fields(form)
        fields.update(
            {"username": self._username, "password": self._password, "blogin": "login"}
        )
        action = urljoin(url, form.get("action") or "login.action")
        url, html = await self._request(
            "POST", action, data=_multipart(fields), headers={"Referer": LOGIN_URL}
        )
        self._dump("02_login_post", html)

        if self._is_login_page(url, html):
            soup = BeautifulSoup(html, "html.parser")
            err = soup.select_one(".errorMessage, .alert-danger, .actionError")
            msg = err.get_text(" ", strip=True) if err else "login rifiutato"
            raise ItalgasAuthError(msg)

        self._logged_in = True
        _LOGGER.debug("Login Italgas OK")

    # -------------------------------------------------------------- forniture
    async def get_supplies(self) -> list[Supply]:
        """Forniture associate all'account (pagina Letture)."""
        _, html = await self._get_authenticated(SUPPLIES_URL)
        self._dump("03_forniture", html)
        soup = BeautifulSoup(html, "html.parser")
        supplies: dict[str, Supply] = {}
        for btn in soup.select('[data-navigate-to*="elencoLetture.action?id="]'):
            rid = btn["data-navigate-to"].split("id=", 1)[1]
            # risale fino al blocco della fornitura che contiene il PdR
            card = btn
            pdr = None
            while card is not None and card.name not in ("tr", "body"):
                card = card.parent
            text = card.get_text(" ", strip=True) if card is not None else ""
            m = re.search(r"PdR\s+(\d{14})", text)
            if m:
                pdr = m.group(1)
            if not pdr or pdr in supplies:
                continue
            meter = re.search(r"Matricola contatore\s+(\S+)", text)
            supplies[pdr] = Supply(
                pdr=pdr,
                readings_id=rid,
                meter=meter.group(1) if meter else None,
            )
        _LOGGER.debug("Forniture trovate: %s", list(supplies))
        return list(supplies.values())

    async def get_supply(self) -> Supply:
        supplies = await self.get_supplies()
        if not supplies:
            raise ItalgasError("Nessuna fornitura associata all'account")
        if self.pdr is None:
            return supplies[0]
        for s in supplies:
            if s.pdr == self.pdr:
                return s
        raise ItalgasPdrNotFound(
            f"PdR {self.pdr} non trovato (disponibili: {[s.pdr for s in supplies]})"
        )

    # --------------------------------------------------------------- letture
    async def _readings_window(
        self, supply: Supply, start: date, end: date
    ) -> list[Reading] | None:
        """Letture tra start ed end (max ~13 mesi). None se il portale dà errore."""
        page_url, html = await self._get_authenticated(
            urljoin(BASE_URL, f"elencoLetture.action?id={supply.readings_id}")
        )
        form = BeautifulSoup(html, "html.parser").find("form", id="ricercaLetture")
        if form is None:
            raise ItalgasError("Form ricercaLetture non trovato (il sito è cambiato?)")

        fields = _form_fields(form)
        fields["dataDa"] = start.strftime("%d/%m/%Y")
        fields["dataA"] = end.strftime("%d/%m/%Y")
        action = urljoin(page_url, form.get("action") or "ricercaLetture.action")
        url, html = await self._request(
            "POST", action, data=_multipart(fields), headers={"Referer": page_url}
        )
        tag = f"{start:%Y%m%d}_{end:%Y%m%d}"
        self._dump(f"04_letture_{tag}", html)

        soup = BeautifulSoup(html, "html.parser")
        if "Errore di sistema" in html:
            _LOGGER.debug("Errore di sistema per %s - %s", start, end)
            return None

        csv_link = next(
            (a["href"] for a in soup.select(".exportlinks a[href]") if "-e=1" in a["href"]),
            None,
        )
        if csv_link:
            _, body = await self._request("GET", urljoin(url, csv_link))
            self._dump(f"05_letture_{tag}", body, "csv")
            if not body.lstrip("﻿").startswith("<"):
                return self._parse_csv(body)
        # fallback: solo la prima pagina della tabella HTML
        return self._parse_table(soup)

    @staticmethod
    def _parse_csv(body: str) -> list[Reading]:
        out: list[Reading] = []
        reader = csv.DictReader(io.StringIO(body.lstrip("﻿")), delimiter=";")
        for row in reader:
            row = {(k or "").strip().lower(): (v or "").strip() for k, v in row.items()}
            d = _parse_date(row.get("data lettura", ""))
            v = _parse_number(row.get("lettura", ""))
            if d is None or v is None:
                continue
            out.append(
                Reading(
                    date=d,
                    value=v,
                    kind=row.get("tipologia lettura") or None,
                    meter=row.get("matricola contatore") or None,
                    raw=row,
                )
            )
        return out

    @staticmethod
    def _parse_table(soup: BeautifulSoup) -> list[Reading]:
        out: list[Reading] = []
        for table in soup.find_all("table"):
            headers = [th.get_text(" ", strip=True).lower() for th in table.find_all("th")]
            if not any(h.startswith("data lettura") for h in headers):
                continue
            idx = {
                "meter": next((i for i, h in enumerate(headers) if "matricola" in h), None),
                "date": next(i for i, h in enumerate(headers) if h.startswith("data lettura")),
                "value": next((i for i, h in enumerate(headers) if h == "lettura"), None),
                "kind": next((i for i, h in enumerate(headers) if h.startswith("tipologia")), None),
            }
            if idx["value"] is None:
                continue
            for tr in table.find_all("tr"):
                cells = [td.get_text(" ", strip=True) for td in tr.find_all("td")]
                if len(cells) < len(headers):
                    continue
                d, v = _parse_date(cells[idx["date"]]), _parse_number(cells[idx["value"]])
                if d is None or v is None:
                    continue
                out.append(
                    Reading(
                        date=d,
                        value=v,
                        kind=cells[idx["kind"]] if idx["kind"] is not None else None,
                        meter=cells[idx["meter"]] if idx["meter"] is not None else None,
                    )
                )
        return out

    async def get_readings(
        self, start: date | None = None, end: date | None = None
    ) -> list[Reading]:
        """Letture (ordinate per data) tra start ed end, a finestre di 12 mesi.

        Va indietro nel tempo e si ferma alla prima finestra vuota o in errore.
        """
        end = end or date.today()
        start = start or (end - timedelta(days=WINDOW_DAYS))
        supply = await self.get_supply()
        if self.pdr is None:
            self.pdr = supply.pdr

        by_date: dict[date, Reading] = {}
        win_end = end
        while win_end > start:
            win_start = max(start, win_end - timedelta(days=WINDOW_DAYS))
            rows = await self._readings_window(supply, win_start, win_end)
            if not rows:
                break
            for r in rows:
                by_date.setdefault(r.date, r)
            win_end = win_start - timedelta(days=1)

        return sorted(by_date.values(), key=lambda r: r.date)


def period_consumption(readings: list[Reading]) -> list[tuple[date, float]]:
    """Differenze tra letture consecutive -> consumo per periodo (m³)."""
    return [
        (cur.date, round(cur.value - prev.value, 3))
        for prev, cur in zip(readings, readings[1:])
    ]
