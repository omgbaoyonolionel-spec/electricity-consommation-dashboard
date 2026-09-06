"""
Collecteur Shelly Pro 3EM -> PostgreSQL (table shelly_readings).

Variables d'environnement : SHELLY_NAME, SHELLY_IP, SHELLY_LOOP (s), PG_DSN.
Cadence à rendez-vous absolus ; compteurs d'énergie lus 1 cycle sur 10.
"""
import asyncio
import logging
import os
from datetime import datetime, timezone

import aiohttp
import asyncpg

NAME = os.environ.get("SHELLY_NAME", "tableau")
IP = os.environ["SHELLY_IP"]
LOOP_S = float(os.environ.get("SHELLY_LOOP", "1"))
PG_DSN = os.environ["PG_DSN"]
PHASES = {"a": "A", "b": "B", "c": "C"}

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("shelly")

SQL = """
INSERT INTO shelly_readings
  (device_name, phase, "timestamp", act_power_w, aprt_power_va, current_a,
   voltage_v, power_factor, frequency_hz, act_energy_wh, act_ret_energy_wh)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
"""


async def lire(http: aiohttp.ClientSession, path: str) -> dict:
    url = f"http://{IP}{path}"
    async with http.get(url, timeout=aiohttp.ClientTimeout(total=3)) as r:
        return await r.json()


async def run() -> None:
    pool = await asyncpg.create_pool(PG_DSN, min_size=1, max_size=2)
    async with aiohttp.ClientSession() as http:
        log.info("Collecte Shelly %s (%s) toutes les %ss", NAME, IP, LOOP_S)
        emdata = None
        cycle = 0
        prochain = asyncio.get_event_loop().time()
        while True:
            prochain += LOOP_S
            try:
                em = await lire(http, "/rpc/EM.GetStatus?id=0")
                if emdata is None or cycle % 10 == 0:
                    emdata = await lire(http, "/rpc/EMData.GetStatus?id=0")
                ts = datetime.now(timezone.utc)
                rows = [
                    (NAME, P, ts,
                     em[f"{p}_act_power"], em[f"{p}_aprt_power"],
                     em[f"{p}_current"], em[f"{p}_voltage"],
                     em[f"{p}_pf"], em[f"{p}_freq"],
                     emdata[f"{p}_total_act_energy"],
                     emdata[f"{p}_total_act_ret_energy"])
                    for p, P in PHASES.items()
                ]
                async with pool.acquire() as cx:
                    await cx.executemany(SQL, rows)
                if cycle % 30 == 0:
                    log.info("A=%.0f W  B=%.0f W  C=%.0f W  total=%.0f W",
                             em["a_act_power"], em["b_act_power"],
                             em["c_act_power"], em["total_act_power"])
            except Exception as e:
                log.warning("cycle ignoré : %s", e)
            cycle += 1
            await asyncio.sleep(
                max(0.0, prochain - asyncio.get_event_loop().time()))


if __name__ == "__main__":
    asyncio.run(run())