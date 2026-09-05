-- ============================================================================
-- ETAPE 2 (AQ donnees P1) : architecture en zones Bronze/Silver/Quarantaine/Gold
-- Idempotent. Version 1.0.0. Prerequis : etape 1 (dictionnaire) executee.
-- ============================================================================

COMMENT ON SCHEMA shelly IS
'ZONE BRONZE (flux P1) : p1_raw_rpc (payloads scelles), p1_collection_cycle,
p1_instantaneous_observation, p1_variable_registry. REGLE : insertion seule,
jamais UPDATE/DELETE manuel. Les defauts y restent. Retention : voir
silver.dq_config.';
COMMENT ON TABLE shelly_minute IS
'ZONE BRONZE (verite energetique) : memoire integree de l''appareil, 1 ligne
par minute. Insertion idempotente par shelly_history. Jamais de correction en
place. Abonnement MONOPHASE : voie A = total (sortie differentiel), B et C =
parties incluses dans A. Colonnes n_* sans signification. Anomalies connues
documentees dans quarantaine.enregistrements.';

CREATE SCHEMA IF NOT EXISTS silver;
COMMENT ON SCHEMA silver IS
'ZONE SILVER : donnees typees, temps explicite (local+UTC), drapeaux dq_* A
COTE des valeurs, jamais a la place. AUCUNE valeur inventee (ni interpolation
ni imputation).';

CREATE TABLE IF NOT EXISTS silver.dq_config (
    cle         TEXT PRIMARY KEY,
    valeur      TEXT NOT NULL,
    unite       TEXT,
    commentaire TEXT,
    version     TEXT NOT NULL DEFAULT '1.0.0',
    maj_le      DATE NOT NULL DEFAULT CURRENT_DATE
);
INSERT INTO silver.dq_config (cle, valeur, unite, commentaire) VALUES
 ('version_regles',            '1.0.0', NULL,   'version globale des regles de zone'),
 ('chain_rel_tol',             '0.05',  'ratio','tolerance p_min <= p_moy <= p_max'),
 ('datation_load_min_w',       '100',   'W',    'charge minimale pour la regle de datation'),
 ('offset_horloge_alerte_ms',  '2000',  'ms',   'au-dela : drapeau derive horloge'),
 ('divergence_methodes_tol',   '0.001', 'abs',  'tolerance GetStatus vs GetComponents (hors rssi)'),
 ('retention_bronze_payloads', '2',     'jours','p1_raw_rpc : purge au-dela (politique ecrite)'),
 ('retention_bronze_observations','7',  'jours','p1_instantaneous_observation : purge au-dela'),
 ('retention_bronze_minute',   'illimitee', NULL,'shelly_minute : conservation permanente'),
 ('retention_gold',            'recalculable', NULL,'Gold jetable : regenerable depuis Silver')
ON CONFLICT (cle) DO UPDATE SET valeur = EXCLUDED.valeur,
    unite = EXCLUDED.unite, commentaire = EXCLUDED.commentaire;

CREATE OR REPLACE VIEW silver.p1_seconde AS
WITH par_variable AS (
    SELECT o.cycle_id, r.variable_name,
           MAX(o.numeric_value) FILTER (WHERE o.rpc_method = 'Shelly.GetStatus')     AS v_status,
           MAX(o.numeric_value) FILTER (WHERE o.rpc_method = 'Shelly.GetComponents') AS v_components,
           MAX(o.clock_offset_ms) AS offset_ms,
           STRING_AGG(DISTINCT o.quality_status, ',') AS qualite
    FROM shelly.p1_instantaneous_observation o
    JOIN shelly.p1_variable_registry r USING (variable_id)
    GROUP BY o.cycle_id, r.variable_name
)
SELECT c.cycle_id,
       c.scheduled_at                                   AS instant_utc,
       c.scheduled_at AT TIME ZONE 'Africa/Douala'      AS instant_local,
       ROUND(AVG(p.v_status) FILTER (WHERE p.variable_name='a_act_power')::numeric,1)  AS a_act_power_w,
       ROUND(AVG(p.v_status) FILTER (WHERE p.variable_name='b_act_power')::numeric,1)  AS b_act_power_w,
       ROUND(AVG(p.v_status) FILTER (WHERE p.variable_name='c_act_power')::numeric,1)  AS c_act_power_w,
       ROUND(AVG(p.v_status) FILTER (WHERE p.variable_name='a_aprt_power')::numeric,1) AS a_aprt_power_va,
       ROUND(AVG(p.v_status) FILTER (WHERE p.variable_name='a_current')::numeric,3)    AS a_current_a,
       ROUND(AVG(p.v_status) FILTER (WHERE p.variable_name='a_voltage')::numeric,1)    AS a_voltage_v,
       ROUND(AVG(p.v_status) FILTER (WHERE p.variable_name='a_pf')::numeric,2)         AS a_pf,
       ROUND(AVG(p.v_status) FILTER (WHERE p.variable_name='a_freq')::numeric,2)       AS a_freq_hz,
       ROUND(AVG(p.v_status) FILTER (WHERE p.variable_name='rssi')::numeric)           AS rssi_db,
       MAX(p.offset_ms)                                                                AS dq_offset_ms,
       MAX(p.offset_ms) > (SELECT valeur::numeric FROM silver.dq_config
                           WHERE cle='offset_horloge_alerte_ms')                       AS dq_derive_horloge,
       BOOL_OR(p.variable_name <> 'rssi'
               AND p.v_status IS NOT NULL AND p.v_components IS NOT NULL
               AND ABS(p.v_status - p.v_components) >
                   (SELECT valeur::numeric FROM silver.dq_config
                    WHERE cle='divergence_methodes_tol'))                              AS dq_divergence_methodes,
       STRING_AGG(DISTINCT p.qualite, ',')                                             AS dq_qualite_source
FROM shelly.p1_collection_cycle c
JOIN par_variable p USING (cycle_id)
GROUP BY c.cycle_id, c.scheduled_at;
COMMENT ON VIEW silver.p1_seconde IS
'SILVER seconde : consolidation 40->20 (methode GetStatus retenue, divergence
controlee et drapeautee), temps local+UTC, drapeaux dq_*. Source : Bronze P1.';

CREATE OR REPLACE VIEW silver.minute AS
SELECT m.ts                                        AS minute_utc,
       m.ts AT TIME ZONE 'Africa/Douala'           AS minute_locale,
       m.a_total_act_energy, m.a_total_act_energy * 60 AS a_p_moy_w,
       m.a_min_act_power, m.a_max_act_power,
       m.a_avg_current, m.a_max_current, m.a_avg_voltage, m.a_min_voltage,
       m.b_total_act_energy, m.b_max_act_power,
       m.c_total_act_energy, m.c_max_act_power,
       (m.a_max_act_power > (SELECT valeur::numeric FROM silver.dq_config WHERE cle='datation_load_min_w')
        AND m.a_total_act_energy * 60 > m.a_max_act_power *
            (1 + (SELECT valeur::numeric FROM silver.dq_config WHERE cle='chain_rel_tol')))
                                                   AS dq_moyenne_sup_max,
       (m.a_max_act_power > (SELECT valeur::numeric FROM silver.dq_config WHERE cle='datation_load_min_w')
        AND m.a_total_act_energy * 60 < m.a_min_act_power *
            (1 - (SELECT valeur::numeric FROM silver.dq_config WHERE cle='chain_rel_tol')))
                                                   AS dq_moyenne_inf_min,
       (m.a_max_act_power < -50)                   AS dq_polarite_inversee
FROM shelly_minute m;
COMMENT ON VIEW silver.minute IS
'SILVER minute : verite energetique typee et drapeautee. Valeurs originales
intactes ; drapeaux dq_* calcules par les regles de silver.dq_config.';

CREATE SCHEMA IF NOT EXISTS quarantaine;
COMMENT ON SCHEMA quarantaine IS
'ZONE QUARANTAINE : enregistrements que l''automate n''a pas le droit de
trancher. Chaque entree attend une decision humaine signee. Rien n''est
retire de Bronze.';
CREATE TABLE IF NOT EXISTS quarantaine.enregistrements (
    id               BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source_table     TEXT NOT NULL,
    cle_origine      TEXT NOT NULL,
    ligne_origine    JSONB NOT NULL,
    regle_enfreinte  TEXT NOT NULL,
    version_regle    TEXT NOT NULL,
    gravite          TEXT NOT NULL CHECK (gravite IN ('CRITICAL','MAJOR')),
    explication      TEXT NOT NULL,
    recommandation   TEXT,
    statut           TEXT NOT NULL DEFAULT 'EN_ATTENTE_VALIDATION_HUMAINE'
                     CHECK (statut IN ('EN_ATTENTE_VALIDATION_HUMAINE',
                                       'EXCLU_ANALYSE','REQUALIFIE_VALIDE',
                                       'CORRIGE_TRACE')),
    decision         TEXT,
    decide_par       TEXT,
    decide_le        DATE,
    detecte_le       TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (source_table, cle_origine, regle_enfreinte)
);

INSERT INTO quarantaine.enregistrements
    (source_table, cle_origine, ligne_origine, regle_enfreinte, version_regle,
     gravite, explication, recommandation)
SELECT 'shelly_minute', m.ts::text, to_jsonb(m),
       CASE WHEN m.a_total_act_energy*60 > m.a_max_act_power*1.05
            THEN 'MIN-002 moyenne > max instantane'
            ELSE 'ELE-006 polarite inversee' END,
       (SELECT valeur FROM silver.dq_config WHERE cle='version_regles'),
       'MAJOR',
       CASE WHEN m.a_total_act_energy*60 > m.a_max_act_power*1.05
            THEN 'Recalage d''horloge appareil : energie versee dans une minute voisine'
            ELSE 'Pince A montee inversee a l''installation (31/08 soir)' END,
       'Ecarter des agregats ; ne pas corriger en Bronze'
FROM shelly_minute m
WHERE (m.a_max_act_power > 100 AND m.a_total_act_energy*60 > m.a_max_act_power*1.05)
   OR (m.a_max_act_power < -50)
ON CONFLICT (source_table, cle_origine, regle_enfreinte) DO NOTHING;

CREATE SCHEMA IF NOT EXISTS gold;
COMMENT ON SCHEMA gold IS
'ZONE GOLD : agregats prets a l''usage. Regles : chaque chiffre porte sa
couverture ; tout objet Gold est regenerable depuis Silver (jetable).';

CREATE OR REPLACE VIEW gold.bilan_journalier AS
SELECT (s.minute_locale)::date                              AS jour,
       COUNT(*)                                             AS minutes_mesurees,
       1440 - COUNT(*)                                      AS minutes_absentes,
       ROUND(100.0 * COUNT(*) / 1440, 1)                    AS couverture_pct,
       ROUND(SUM(s.a_total_act_energy)::numeric / 1000, 2)  AS kwh_total_A,
       ROUND(SUM(s.b_total_act_energy)::numeric / 1000, 2)  AS kwh_partie_B,
       ROUND(MAX(s.a_max_act_power) FILTER (WHERE NOT s.dq_moyenne_sup_max)::numeric) AS p_pointe_w,
       ROUND(MAX(s.a_max_current)::numeric, 1)              AS i_max_a,
       ROUND(MIN(s.a_min_voltage) FILTER (WHERE s.a_min_voltage > 50)::numeric, 1) AS u_min_v,
       COUNT(*) FILTER (WHERE s.dq_moyenne_sup_max OR s.dq_moyenne_inf_min
                           OR s.dq_polarite_inversee)       AS minutes_drapeautees,
       (SELECT valeur FROM silver.dq_config WHERE cle='version_regles') AS version_regles
FROM silver.minute s
GROUP BY 1;
COMMENT ON VIEW gold.bilan_journalier IS
'GOLD : bilan par jour AVEC couverture et minutes drapeautees. Pointe calculee
hors minutes incoherentes (regle silver). Regenerable : ne jamais archiver.';

CREATE OR REPLACE VIEW gold.profil_horaire AS
SELECT (s.minute_locale)::date                             AS jour,
       EXTRACT(hour FROM s.minute_locale)::int             AS heure,
       COUNT(*)                                            AS minutes,
       ROUND(SUM(s.a_total_act_energy)::numeric / 1000, 3) AS kwh,
       ROUND(MAX(s.a_max_act_power)::numeric)              AS p_max_w
FROM silver.minute s
GROUP BY 1, 2;
COMMENT ON VIEW gold.profil_horaire IS
'GOLD : profil horaire avec compte de minutes (couverture par heure).';
