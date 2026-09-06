"""
Collecteur d'historique Shelly Pro 3EM -> PostgreSQL (shelly_minute).
Rattrapage automatique, idempotent, filtre TS_MIN ; backoff et redécouverte d'adresse.
Env : SHELLY_IP, SHELLY_SYNC_S (60), SHELLY_CHUNK_S (21600), SHELLY_TS_MIN, PG_DSN
      (+ SHELLY_MAC/HOST/SUBNET pour la découverte).
"""
import asyncio
import logging
import os
import time
from datetime import datetime, timezone

import aiohttp
import asyncpg

from shelly_discovery import decouvrir

SYNC_S = int(os.environ.get("SHELLY_SYNC_S", "60"))
CHUNK_S = int(os.environ.get("SHELLY_CHUNK_S", "21600"))
TS_MIN = int(datetime.fromisoformat(os.environ.get("SHELLY_TS_MIN", "2026-08-31"))
             .replace(tzinfo=timezone.utc).timestamp())
PG_DSN = os.environ["PG_DSN"]
TABLE = "shelly_minute"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("shelly_history")


def utc(ts: int) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%d/%m %H:%M")


class Liaison:
    def __init__(self, http: aiohttp.ClientSession, ip: str | None) -> None:
        self.http, self.ip, self.echecs, self.hs_depuis = http, ip, 0, None

    async def lire(self, path: str) -> dict:
        async with self.http.get(f"http://{self.ip}{path}",
                                 timeout=aiohttp.ClientTimeout(total=30)) as r:
            r.raise_for_status()
            return await r.json(content_type=None)

    def succes(self) -> None:
        if self.echecs:
            duree = (datetime.now(timezone.utc) - self.hs_depuis).total_seconds()
            log.info("Liaison rétablie avec %s après %.0f s", self.ip, duree)
        self.echecs, self.hs_depuis = 0, None

    async def echec(self, err: Exception) -> float:
        self.echecs += 1
        if self.echecs == 1:
            self.hs_depuis = datetime.now(timezone.utc)
            log.warning("Shelly injoignable à %s : %s", self.ip, err)
        if self.echecs % 3 == 0:
            nouvelle = await decouvrir(self.http, self.ip)
            if nouvelle and nouvelle != self.ip:
                log.warning("Adresse du Shelly changée : %s -> %s", self.ip, nouvelle)
                self.ip = nouvelle
        return min(300.0, SYNC_S * 2.0 ** min(self.echecs, 3))


async def colonnes_table(cx) -> set[str]:
    rows = await cx.fetch(
        "SELECT column_name FROM information_schema.columns WHERE table_name = $1", TABLE)
    return {r["column_name"] for r in rows}


def aplatir(rep: dict) -> tuple[list[str], list[tuple[int, int, list]]]:
    keys, minutes = rep.get("keys", []), []
    for bloc in rep.get("data", []):
        ts0, period = int(bloc["ts"]), int(bloc.get("period", 60))
        for i, valeurs in enumerate(bloc.get("values", [])):
            minutes.append((ts0 + i * period, period, valeurs))
    return keys, minutes


async def inserer(cx, mac, keys, minutes, cols_table) -> int:
    idx = [(i, k) for i, k in enumerate(keys) if k in cols_table]
    if not idx:
        return 0
    cols = ", ".join(["device_mac", "ts", "period_s"] + [k for _, k in idx])
    params = ", ".join(f"${n}" for n in range(1, len(idx) + 4))
    sql = f"INSERT INTO {TABLE} ({cols}) VALUES ({params}) ON CONFLICT (device_mac, ts) DO NOTHING"
    rows = [(mac, datetime.fromtimestamp(ts, tz=timezone.utc), period,
             *[v[i] if i < len(v) else None for i, _ in idx])
            for ts, period, v in minutes if ts >= TS_MIN]
    if rows:
        await cx.executemany(sql, rows)
    return len(rows)


async def synchroniser(liaison: Liaison, pool, mac: str, cols_table: set[str]) -> int:
    async with pool.acquire() as cx:
        dernier = await cx.fetchval(f"SELECT MAX(ts) FROM {TABLE} WHERE device_mac = $1", mac)
    if dernier is None:
        recs = await liaison.lire("/rpc/EMData.GetRecords?id=0")
        blocs = [b for b in recs.get("data_blocks", []) if int(b["ts"]) >= TS_MIN]
        if not blocs:
            return 0
        debut = int(blocs[0]["ts"])
        log.info("Base vide : rattrapage depuis %s UTC", utc(debut))
    else:
        debut = int(dernier.timestamp()) + 60
    total, borne = 0, int(time.time()) - 60
    while debut <= borne:
        fin, curseur = min(debut + CHUNK_S, borne), debut
        while curseur is not None and curseur <= fin:
            rep = await liaison.lire(
                f"/rpc/EMData.GetData?id=0&ts={curseur}&end_ts={fin}&add_keys=true")
            keys, minutes = aplatir(rep)
            if minutes:
                async with pool.acquire() as cx:
                    total += await inserer(cx, mac, keys, minutes, cols_table)
            suivant = rep.get("next_record_ts")
            curseur = int(suivant) if suivant and int(suivant) > curseur else None
        debut = fin + 60
    return total


async def run() -> None:
    pool = await asyncpg.create_pool(PG_DSN, min_size=1, max_size=2)
    async with pool.acquire() as cx:
        cols_table = await colonnes_table(cx)
    async with aiohttp.ClientSession() as http:
        liaison = Liaison(http, os.environ.get("SHELLY_IP"))
        liaison.ip = await decouvrir(http, liaison.ip) or liaison.ip
        mac = None
        while True:
            try:
                if mac is None:
                    info = await liaison.lire("/rpc/Shelly.GetDeviceInfo")
                    mac = info["mac"]
                    log.info("Historique Shelly %s (%s, fw %s) — sync %ss, TS_MIN=%s",
                             info["id"], liaison.ip, info.get("ver"), SYNC_S, utc(TS_MIN))
                n = await synchroniser(liaison, pool, mac, cols_table)
                liaison.succes()
                if n:
                    log.info("Sync : %d minute(s) ajoutée(s)", n)
                await asyncio.sleep(SYNC_S)
            except Exception as e:
                await asyncio.sleep(await liaison.echec(e))


if __name__ == "__main__":
    asyncio.run(run())
    