# Italgas per Home Assistant

Integrazione custom che legge le letture del contatore gas dal portale
[clienti.italgas.it](https://clienti.italgas.it). Il portale non ha API pubbliche:
l'integrazione fa login e legge la pagina `ricercaLetture.action` (scraping).

## Sensori
- **Lettura contatore** (m³, `total_increasing`)
- **Data ultima lettura**
- **Consumo ultimo periodo** (differenza tra le ultime due letture, con storico negli attributi)

Aggiornamento ogni 12 ore (le letture sono mensili).

## Statistiche storiche (dashboard Energia)
Oltre ai sensori, l'integrazione importa le letture come statistica esterna
`italgas:gas_<PdR>` (nome "Gas <PdR>"), datata al giorno reale di ogni lettura:
- al primo avvio scarica tutto lo storico disponibile sul portale;
- agli aggiornamenti successivi aggiunge solo le letture nuove.

Per usarla: Impostazioni → Dashboard → Energia → Consumo gas → aggiungi
**Gas <PdR>** (non il sensore "Lettura contatore", che registrerebbe i consumi
nel giorno in cui HA scarica la lettura e non nel mese corretto).

Se la lettura scende (contatore sostituito) il nuovo contatore viene considerato
ripartito da zero.

## Installazione
Copia `custom_components/italgas` in `<config>/custom_components/`, riavvia HA e
aggiungi l'integrazione "Italgas" da Impostazioni → Dispositivi e servizi.

## Sviluppo / test
```bash
python3 -m venv .venv && .venv/bin/pip install aiohttp beautifulsoup4
# compila credentials.json (escluso da git)
.venv/bin/python scripts/test_italgas.py --login   # solo login
.venv/bin/python scripts/test_italgas.py           # login + letture
```
Le pagine HTML scaricate vengono salvate in `debug/` per analizzare la struttura.

Test dentro Home Assistant (il test end-to-end usa `credentials.json` e il portale reale):
```bash
python3 -m venv .venv-test && .venv-test/bin/pip install pytest-homeassistant-custom-component beautifulsoup4
.venv-test/bin/python -m pytest -q
```
