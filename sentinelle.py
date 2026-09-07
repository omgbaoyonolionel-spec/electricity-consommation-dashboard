# -*- coding: utf-8 -*-
"""Sentinelle Shelly : tests + alertes + reconciliation + sonde, chaque heure. v1.0.0"""
import os, time, json, urllib.request
from datetime import datetime, timezone
import psycopg2

DSN = os.getenv("PG_DSN", "postgresql://tapo:" + os.getenv("POSTGRES_PASSWORD", "") + "@postgres:5432/tapo")
SHELLY_IP = os.getenv("SHELLY_IP", "")
ALERT_DIR = "/alertes"

def verdict(cur, cat, nom, statut, valeur=None, seuil=None, detail=None):
    cur.execute("INSERT INTO monitoring.verdicts (categorie, nom, statut, valeur, seuil, detail) VALUES (%s,%s,%s,%s,%s,%s)",
                (cat, nom, statut, valeur, seuil, detail))
    print(datetime.now(timezone.utc).isoformat(), cat, nom, statut, valeur, flush=True)

def rpc(methode):
    with urllib.request.urlopen("http://" + SHELLY_IP + "/rpc/" + methode, timeout=8) as r:
        return json.loads(r.read().decode())

def alerte_fichier(niveau, texte):
    try:
        chemin = os.path.join(ALERT_DIR, "ALERTE_SHELLY_QUALITE.txt")
        with open(chemin, "a", encoding="ascii", errors="replace") as f:
            f.write(datetime.now(timezone.utc).isoformat() + " [" + niveau + "] " + texte + "\n")
    except Exception:
        pass

def cycle(cur):
    # --- ALERTE P2_RETARD_MEMOIRE (>10 min) + P1_OFFLINE (croise 2 chaines)
    cur.execute("SELECT ROUND(EXTRACT(EPOCH FROM now()-MAX(ts))/60,1) FROM shelly_minute")
    retard = float(cur.fetchone()[0])
    cur.execute("SELECT ROUND(EXTRACT(EPOCH FROM now()-MAX(scheduled_at))) FROM shelly.p1_collection_cycle WHERE cycle_status='success'")
    p1_age = float(cur.fetchone()[0])
    if p1_age > 120 and retard > 5:
        verdict(cur, "ALERTE", "P1_CAPTEUR_OFFLINE", "ALERTE", p1_age, "120s et 5min", "2 chaines muettes")
        alerte_fichier("P1", "capteur offline : P1 " + str(p1_age) + "s, memoire " + str(retard) + "min")
    else:
        verdict(cur, "ALERTE", "P1_CAPTEUR_OFFLINE", "OK", p1_age, "120s")
    statut_retard = "ALERTE" if retard > 10 else "OK"
    verdict(cur, "ALERTE", "P2_RETARD_MEMOIRE", statut_retard, retard, "10 min")
    if statut_retard == "ALERTE":
        alerte_fichier("P2", "retard memoire " + str(retard) + " min")
    # --- ALERTE P2_COUVERTURE (cycles P1, 1h glissante)
    cur.execute("""SELECT ROUND(100.0*COUNT(*) FILTER (WHERE c>=54)/NULLIF(COUNT(*),0),1) FROM
      (SELECT date_trunc('minute',scheduled_at) m, COUNT(*) c FROM shelly.p1_collection_cycle
       WHERE cycle_status='success' AND scheduled_at > now()-interval '1 hour' GROUP BY 1) x""")
    row = cur.fetchone()
    couv = float(row[0]) if row[0] is not None else 0.0
    verdict(cur, "ALERTE", "P2_COUVERTURE_P1", "ALERTE" if couv < 80 else "OK", couv, "80 pct")
    # --- ALERTE P3 tension (excursions heure ecoulee)
    cur.execute("""SELECT COUNT(*) FROM shelly_minute WHERE ts > now()-interval '1 hour'
      AND a_min_voltage > 50 AND (a_min_voltage < 207 OR a_max_voltage > 253)""")
    exc = cur.fetchone()[0]
    verdict(cur, "ALERTE", "P3_TENSION", "INFO" if exc > 0 else "OK", exc, "hors 207..253", "excursions dans l heure")
    # --- TESTS (rejeu sur 24h glissantes)
    cur.execute("""SELECT COUNT(*)*5 - (COUNT(a_total_act_energy)+COUNT(a_min_act_power)+COUNT(a_max_act_power)+COUNT(a_avg_voltage)+COUNT(a_avg_current))
      FROM shelly_minute WHERE ts > now()-interval '24 hours'""")
    verdict(cur, "TEST", "NULL_TX_24H", "PASS" if cur.fetchone()[0] == 0 else "FAIL", None, "0 NULL")
    cur.execute("""SELECT COUNT(*) FROM shelly_minute WHERE ts > now()-interval '24 hours' AND
      ((a_avg_voltage NOT BETWEEN 100 AND 300 AND a_avg_voltage <> 0) OR a_avg_current NOT BETWEEN 0 AND 63
       OR a_max_act_power NOT BETWEEN -14500 AND 14500)""")
    verdict(cur, "TEST", "PLAGE_24H", "PASS" if cur.fetchone()[0] == 0 else "FAIL", None, "plages dq_config")
    cur.execute("""SELECT COUNT(*) FROM shelly_minute m WHERE ts > now()-interval '24 hours'
      AND a_max_act_power > 100 AND (a_total_act_energy*60 > a_max_act_power*1.05 OR a_total_act_energy*60 < a_min_act_power*0.95)
      AND NOT EXISTS (SELECT 1 FROM quarantaine.enregistrements q WHERE q.cle_origine::timestamptz = m.ts)""")
    n_incoh = cur.fetchone()[0]
    verdict(cur, "TEST", "COHERENCE_24H_HORS_QUARANTAINE", "PASS" if n_incoh == 0 else "FAIL", n_incoh, "0 nouvelle")
    if n_incoh > 0:
        alerte_fichier("P3", str(n_incoh) + " incoherence(s) de chaine NON statuee(s) dans les 24h")

def sonde_quotidienne(cur):
    cur.execute("SELECT COUNT(*) FROM monitoring.sondes_compteurs WHERE sonde_le::date = CURRENT_DATE")
    if cur.fetchone()[0] > 0 or not SHELLY_IP:
        return
    try:
        em = rpc("EMData.GetStatus?id=0")
        temp = rpc("Temperature.GetStatus?id=0")
        syss = rpc("Sys.GetStatus")
        cur.execute("""INSERT INTO monitoring.sondes_compteurs (a_total_wh,a_ret_wh,b_total_wh,c_total_wh,c_ret_wh,temperature_c,uptime_s)
          VALUES (%s,%s,%s,%s,%s,%s,%s)""",
          (em.get("a_total_act_energy"), em.get("a_total_act_ret_energy"), em.get("b_total_act_energy"),
           em.get("c_total_act_energy"), em.get("c_total_act_ret_energy"), temp.get("tC"), syss.get("uptime")))
        verdict(cur, "SONDE", "EMDATA_QUOTIDIENNE", "OK", em.get("a_total_act_energy"), None, "compteurs vie consignes")
        tc = temp.get("tC")
        if tc is not None and tc > 60:
            verdict(cur, "ALERTE", "P3_TEMPERATURE", "ALERTE", tc, "60 C")
            alerte_fichier("P3", "temperature appareil " + str(tc) + " C")
        # CROISSANCE (test I2, actif des la 2e sonde)
        cur.execute("SELECT a_total_wh FROM monitoring.sondes_compteurs ORDER BY sonde_le DESC LIMIT 2")
        rows = cur.fetchall()
        if len(rows) == 2:
            verdict(cur, "TEST", "CROISSANCE_COMPTEUR_A", "PASS" if rows[0][0] >= rows[1][0] else "FAIL",
                    float(rows[0][0]) - float(rows[1][0]), ">= 0")
        # RECONCILIATION methode 2 (delta compteurs vs somme minutes entre 2 sondes)
        cur.execute("""SELECT s1.sonde_le, s2.sonde_le, s1.a_total_wh - s2.a_total_wh FROM
          (SELECT * FROM monitoring.sondes_compteurs ORDER BY sonde_le DESC LIMIT 1) s1,
          (SELECT * FROM monitoring.sondes_compteurs ORDER BY sonde_le DESC LIMIT 2) s2
          WHERE s2.sonde_le < s1.sonde_le""")
        r = cur.fetchone()
        if r:
            cur.execute("SELECT COALESCE(SUM(a_total_act_energy),0) FROM shelly_minute WHERE ts > %s AND ts <= %s", (r[1], r[0]))
            somme = float(cur.fetchone()[0])
            delta = float(r[2])
            ecart = abs(delta - somme) / max(delta, 1.0) * 100
            verdict(cur, "RECONCILIATION", "METHODE2_COMPTEURS", "PASS" if ecart <= 2 else "FAIL",
                    round(ecart, 2), "2 pct", "delta compteur " + str(round(delta,1)) + " Wh vs minutes " + str(round(somme,1)))
    except Exception as e:
        verdict(cur, "SONDE", "EMDATA_QUOTIDIENNE", "FAIL", None, None, str(e)[:120])

def main():
    while True:
        try:
            conn = psycopg2.connect(DSN)
            conn.autocommit = True
            cur = conn.cursor()
            cycle(cur)
            sonde_quotidienne(cur)
            cur.close(); conn.close()
        except Exception as e:
            print("ERREUR SENTINELLE:", str(e)[:200], flush=True)
        time.sleep(3600)

if __name__ == "__main__":
    main()
