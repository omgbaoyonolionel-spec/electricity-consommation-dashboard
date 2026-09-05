-- HISTORIQUE P1 : vues d historique reproductibles. Idempotent. v1.0.0
-- (deja appliquees en base via pgAdmin le 03/09 - ce fichier les rend rejouables)
CREATE OR REPLACE VIEW shelly.p1_historique_large AS
SELECT c.scheduled_at AT TIME ZONE 'Africa/Douala' AS cycle_local,
       c.cycle_status,
       ROUND(AVG(o.numeric_value) FILTER (WHERE r.variable_name = 'a_act_power')::numeric, 1)  AS a_act_power_w,
       ROUND(AVG(o.numeric_value) FILTER (WHERE r.variable_name = 'a_aprt_power')::numeric, 1) AS a_aprt_power_va,
       ROUND(AVG(o.numeric_value) FILTER (WHERE r.variable_name = 'a_current')::numeric, 3)    AS a_current_a,
       ROUND(AVG(o.numeric_value) FILTER (WHERE r.variable_name = 'a_voltage')::numeric, 1)    AS a_voltage_v,
       ROUND(AVG(o.numeric_value) FILTER (WHERE r.variable_name = 'a_pf')::numeric, 2)         AS a_pf,
       ROUND(AVG(o.numeric_value) FILTER (WHERE r.variable_name = 'a_freq')::numeric, 2)       AS a_freq_hz,
       ROUND(AVG(o.numeric_value) FILTER (WHERE r.variable_name = 'b_act_power')::numeric, 1)  AS b_act_power_w,
       ROUND(AVG(o.numeric_value) FILTER (WHERE r.variable_name = 'b_aprt_power')::numeric, 1) AS b_aprt_power_va,
       ROUND(AVG(o.numeric_value) FILTER (WHERE r.variable_name = 'b_current')::numeric, 3)    AS b_current_a,
       ROUND(AVG(o.numeric_value) FILTER (WHERE r.variable_name = 'b_voltage')::numeric, 1)    AS b_voltage_v,
       ROUND(AVG(o.numeric_value) FILTER (WHERE r.variable_name = 'b_pf')::numeric, 2)         AS b_pf,
       ROUND(AVG(o.numeric_value) FILTER (WHERE r.variable_name = 'b_freq')::numeric, 2)       AS b_freq_hz,
       ROUND(AVG(o.numeric_value) FILTER (WHERE r.variable_name = 'c_act_power')::numeric, 1)  AS c_act_power_w,
       ROUND(AVG(o.numeric_value) FILTER (WHERE r.variable_name = 'c_aprt_power')::numeric, 1) AS c_aprt_power_va,
       ROUND(AVG(o.numeric_value) FILTER (WHERE r.variable_name = 'c_current')::numeric, 3)    AS c_current_a,
       ROUND(AVG(o.numeric_value) FILTER (WHERE r.variable_name = 'c_voltage')::numeric, 1)    AS c_voltage_v,
       ROUND(AVG(o.numeric_value) FILTER (WHERE r.variable_name = 'c_pf')::numeric, 2)         AS c_pf,
       ROUND(AVG(o.numeric_value) FILTER (WHERE r.variable_name = 'c_freq')::numeric, 2)       AS c_freq_hz,
       ROUND(AVG(o.numeric_value) FILTER (WHERE r.variable_name = 'rssi')::numeric)            AS rssi_db,
       MAX(o.clock_offset_ms)                                                                  AS decalage_ms,
       STRING_AGG(DISTINCT o.quality_status, ',')                                              AS qualite
FROM shelly.p1_instantaneous_observation o
JOIN shelly.p1_variable_registry r USING (variable_id)
JOIN shelly.p1_collection_cycle c USING (cycle_id)
GROUP BY c.cycle_id, c.scheduled_at, c.cycle_status;

CREATE OR REPLACE VIEW shelly.p1_reconstitution_minute AS
SELECT ts AT TIME ZONE 'Africa/Douala' AS minute_locale,
       ROUND((a_total_act_energy * 60)::numeric, 1) AS a_act_power_moy_w_derive,
       ROUND(a_min_act_power::numeric, 1)           AS a_act_power_min_w_mesure,
       ROUND(a_max_act_power::numeric, 1)           AS a_act_power_max_w_mesure,
       ROUND((a_avg_voltage * a_avg_current)::numeric, 1) AS a_aprt_power_moy_va_approx,
       ROUND(a_avg_current::numeric, 3)             AS a_current_moy_a_mesure,
       ROUND(a_avg_voltage::numeric, 1)             AS a_voltage_moy_v_mesure,
       ROUND((a_total_act_energy / NULLIF(sqrt(power(a_total_act_energy, 2)
             + power(a_lag_react_energy + a_lead_react_energy, 2)), 0))::numeric, 2)
                                                    AS a_pf_moy_reconstruit,
       ROUND((b_total_act_energy * 60)::numeric, 1) AS b_act_power_moy_w_derive,
       ROUND(b_max_act_power::numeric, 1)           AS b_act_power_max_w_mesure,
       ROUND(b_avg_current::numeric, 3)             AS b_current_moy_a_mesure,
       ROUND(b_avg_voltage::numeric, 1)             AS b_voltage_moy_v_mesure,
       ROUND((b_total_act_energy / NULLIF(sqrt(power(b_total_act_energy, 2)
             + power(b_lag_react_energy + b_lead_react_energy, 2)), 0))::numeric, 2)
                                                    AS b_pf_moy_reconstruit,
       ROUND((c_total_act_energy * 60)::numeric, 1) AS c_act_power_moy_w_derive,
       ROUND(c_max_act_power::numeric, 1)           AS c_act_power_max_w_mesure,
       ROUND(c_avg_current::numeric, 3)             AS c_current_moy_a_mesure,
       ROUND(c_avg_voltage::numeric, 1)             AS c_voltage_moy_v_mesure,
       NULL::numeric AS freq_hz_indisponible,
       NULL::numeric AS rssi_db_indisponible
FROM shelly_minute;
