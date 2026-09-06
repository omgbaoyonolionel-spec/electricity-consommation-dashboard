-- dash_live_views.sql — vues "live" pour pgAdmin sur tapo_readings
-- Exécution : Get-Content .\dash_live_views.sql -Raw | docker exec -i tapo_postgres psql -U tapo -d tapo

CREATE OR REPLACE VIEW public.dash_live_etat AS
WITH p AS (SELECT 'Africa/Douala'::text AS tz, 118::numeric AS prix_kwh, 1::numeric AS seuil_w),
last AS (
    SELECT DISTINCT ON (device_name) device_name, ip, "timestamp", current_power_mw, today_energy_wh, month_energy_wh, on_state
    FROM tapo_readings ORDER BY device_name, "timestamp" DESC
)
SELECT l.device_name AS prise, l."timestamp" AT TIME ZONE p.tz AS derniere_mesure,
       ROUND(EXTRACT(EPOCH FROM now() - l."timestamp") / 60, 1) AS anciennete_min,
       CASE WHEN now() - l."timestamp" > interval '15 min' THEN 'OFFLINE'
            WHEN l.current_power_mw / 1000.0 > p.seuil_w THEN 'EN MARCHE' ELSE 'VEILLE / ARRÊT' END AS etat,
       l.on_state AS relais_on, ROUND(l.current_power_mw / 1000.0, 1) AS puissance_w,
       ROUND(l.today_energy_wh / 1000.0, 3) AS kwh_aujourdhui, ROUND(l.today_energy_wh / 1000.0 * p.prix_kwh, 0) AS fcfa_aujourdhui,
       ROUND(l.month_energy_wh / 1000.0, 2) AS kwh_mois, ROUND(l.month_energy_wh / 1000.0 * p.prix_kwh, 0) AS fcfa_mois
FROM last l, p ORDER BY l.device_name;

CREATE OR REPLACE VIEW public.dash_live_puissance_24h AS
WITH p AS (SELECT 'Africa/Douala'::text AS tz)
SELECT date_trunc('minute', "timestamp" AT TIME ZONE p.tz) AS minute, device_name AS prise,
       ROUND(AVG(current_power_mw) / 1000.0, 1) AS p_moy_w, ROUND(MAX(current_power_mw) / 1000.0, 1) AS p_max_w, COUNT(*) AS n
FROM tapo_readings, p WHERE "timestamp" >= now() - interval '24 hours'
GROUP BY 1, 2 ORDER BY 1, 2;

CREATE OR REPLACE VIEW public.dash_live_energie_jour AS
WITH p AS (SELECT 'Africa/Douala'::text AS tz, 118::numeric AS prix_kwh)
SELECT ("timestamp" AT TIME ZONE p.tz)::date AS jour, device_name AS prise,
       ROUND(MAX(today_energy_wh) / 1000.0, 3) AS kwh, ROUND(MAX(today_energy_wh) / 1000.0 * p.prix_kwh, 0) AS fcfa,
       ROUND(AVG(current_power_mw) / 1000.0, 1) AS p_moy_w, ROUND(MAX(current_power_mw) / 1000.0, 1) AS p_max_w,
       COUNT(*) AS n_mesures, ROUND(100.0 * COUNT(DISTINCT date_trunc('minute', "timestamp")) / 1440, 1) AS dispo_pct
FROM tapo_readings, p GROUP BY 1, 2, p.prix_kwh ORDER BY 1, 2;

CREATE OR REPLACE VIEW public.dash_live_energie_heure AS
WITH p AS (SELECT 'Africa/Douala'::text AS tz, 60::numeric AS trou_s),
r AS (
    SELECT device_name, "timestamp" AT TIME ZONE p.tz AS ts_l, current_power_mw / 1000.0 AS p_w,
           EXTRACT(EPOCH FROM LEAD("timestamp") OVER (PARTITION BY device_name ORDER BY "timestamp") - "timestamp") AS dt_s
    FROM tapo_readings, p
)
SELECT date_trunc('hour', r.ts_l) AS heure, r.device_name AS prise,
       ROUND(SUM(r.p_w * r.dt_s / 3600) FILTER (WHERE r.dt_s <= p.trou_s), 1) AS wh,
       ROUND(AVG(r.p_w), 1) AS p_moy_w, ROUND(MAX(r.p_w), 1) AS p_max_w,
       ROUND(100.0 * COUNT(DISTINCT date_trunc('minute', r.ts_l)) / 60, 1) AS dispo_pct
FROM r, p GROUP BY 1, 2 ORDER BY 1, 2;

CREATE INDEX IF NOT EXISTS ix_tapo_readings_device_ts ON public.tapo_readings (device_name, "timestamp");