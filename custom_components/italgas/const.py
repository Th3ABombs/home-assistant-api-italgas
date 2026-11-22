"""Costanti dell'integrazione Italgas."""
from datetime import timedelta

DOMAIN = "italgas"
CONF_PDR = "pdr"
DEFAULT_SCAN_INTERVAL = timedelta(hours=12)
# al primo avvio scarica fino a N anni di storico (si ferma prima se il portale
# non ha dati più vecchi)
HISTORY_YEARS = 10
