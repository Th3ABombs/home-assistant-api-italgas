"""Costanti dell'integrazione Italgas."""
from datetime import timedelta

DOMAIN = "italgas"
CONF_PDR = "pdr"
# Ogni quanto il coordinator si "sveglia". Il portale viene contattato solo se
# manca la lettura del mese precedente e comunque al massimo ogni MIN_FETCH_INTERVAL.
DEFAULT_SCAN_INTERVAL = timedelta(hours=6)
MIN_FETCH_INTERVAL = timedelta(hours=24)
# al primo avvio scarica fino a N anni di storico (si ferma prima se il portale
# non ha dati più vecchi)
HISTORY_YEARS = 10
