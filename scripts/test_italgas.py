"""Test manuale del client Italgas fuori da Home Assistant.

Uso:
    .venv/bin/python scripts/test_italgas.py            # login + letture
    .venv/bin/python scripts/test_italgas.py --login    # solo login

Le pagine HTML scaricate finiscono in debug/ (escluso da git) per analizzarle.
"""
import argparse
import asyncio
import importlib.util
import json
import logging
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# carica api.py direttamente, senza passare da __init__.py (che importa HA)
_spec = importlib.util.spec_from_file_location(
    "italgas_api", ROOT / "custom_components" / "italgas" / "api.py"
)
api = importlib.util.module_from_spec(_spec)
sys.modules["italgas_api"] = api
_spec.loader.exec_module(api)


async def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--login", action="store_true", help="prova solo il login")
    p.add_argument("--creds", default=ROOT / "credentials.json")
    p.add_argument("--years", type=float, default=1, help="anni di storico da scaricare")
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="%(levelname)s %(message)s")
    creds = json.loads(Path(args.creds).read_text())
    if "INSERISCI" in creds["username"] + creds["password"]:
        print("Compila prima username e password in credentials.json")
        return 2
    if "INSERISCI" in str(creds.get("pdr", "")):
        creds["pdr"] = None

    client = api.ItalgasClient(
        creds["username"], creds["password"], creds.get("pdr"), debug_dir=ROOT / "debug"
    )
    try:
        await client.login()
        print("Login OK")
        if args.login:
            return 0
        supplies = await client.get_supplies()
        for sp in supplies:
            print(f"Fornitura: PdR {sp.pdr}  matricola {sp.meter}")
        start = date.today() - timedelta(days=int(365 * args.years))
        readings = await client.get_readings(start=start)
        print(f"\n{len(readings)} letture trovate")
        for r in readings:
            print(f"  {r.date}  {r.value:>10.3f} m³  {r.kind or ''}")
        for d, c in api.period_consumption(readings):
            print(f"  consumo fino al {d}: {c} m³")
        return 0 if readings else 1
    except api.ItalgasAuthError as e:
        print(f"Login fallito: {e}")
        return 1
    finally:
        await client.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
