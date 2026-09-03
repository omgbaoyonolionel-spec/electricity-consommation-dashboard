-- ============================================================================
-- ETAPE 1 (AQ donnees P1) : dictionnaire des 40 variables + vue 40->20
-- Idempotent : rejouable sans effet de bord. Version 1.0.0
-- Regle capitale : voie A = TOTAL du menage ; B, C = parties INCLUSES dans A.
-- ============================================================================

CREATE TABLE IF NOT EXISTS shelly.p1_dictionnaire (
    variable_id      TEXT PRIMARY KEY
                     REFERENCES shelly.p1_variable_registry(variable_id),
    grandeur         TEXT NOT NULL,
    definition_fr    TEXT NOT NULL,
    unite            TEXT NOT NULL,
    plage_plausible  NUMRANGE,
    source_seuil     TEXT,
    nature           TEXT NOT NULL
                     CHECK (nature IN ('mesuree','derivee','sans_signification')),
    role_metier      TEXT NOT NULL
                     CHECK (role_metier IN ('mesure_consommation','sous_comptage',
                            'securite','qualite_fourniture',
                            'exploitation_dispositif','temoin')),
    regle_usage      TEXT,
    version          TEXT NOT NULL DEFAULT '1.0.0',
    valide_par       TEXT,
    valide_le        DATE
);

COMMENT ON TABLE shelly.p1_dictionnaire IS
'Dictionnaire des donnees P1 (etape 1 AQ). Topologie pilote monophase :
voie A = phase en sortie du differentiel = TOTAL du menage ;
voies B et C = parties INCLUSES dans A (ne jamais additionner A+B+C) ;
n_current = calcul triphase sans signification ici ; rssi = variable
d exploitation du dispositif, pas une donnee du menage.';

INSERT INTO shelly.p1_dictionnaire
    (variable_id, grandeur, definition_fr, unite, plage_plausible,
     source_seuil, nature, role_metier, regle_usage)
SELECT
    r.variable_id,
    r.variable_name,
    CASE r.variable_name
        WHEN 'a_act_power'  THEN 'Puissance active de la voie A : consommation totale instantanee du menage (P = U x I x cos phi)'
        WHEN 'a_aprt_power' THEN 'Puissance apparente de la voie A : S = U x I, appel brut au reseau'
        WHEN 'a_current'    THEN 'Courant dans la phase unique du foyer (voie A) : a confronter au calibre du disjoncteur d abonne'
        WHEN 'a_voltage'    THEN 'Tension de fourniture au tableau (voie A)'
        WHEN 'a_pf'         THEN 'Facteur de puissance de la voie A, distorsion harmonique incluse'
        WHEN 'a_freq'       THEN 'Frequence du reseau mesuree sur la voie A'
        WHEN 'b_act_power'  THEN 'Puissance active du sous-circuit B, incluse dans A (appareils non identifies)'
        WHEN 'b_aprt_power' THEN 'Puissance apparente du sous-circuit B'
        WHEN 'b_current'    THEN 'Courant du sous-circuit B'
        WHEN 'b_voltage'    THEN 'Tension mesuree sur la voie B (meme conducteur que A : monophase)'
        WHEN 'b_pf'         THEN 'Facteur de puissance du sous-circuit B : PF bas et stable = signature de charge inductive'
        WHEN 'b_freq'       THEN 'Frequence du reseau mesuree sur la voie B'
        WHEN 'c_act_power'  THEN 'Puissance active de la voie C : conducteur sans charge (zero attendu)'
        WHEN 'c_aprt_power' THEN 'Puissance apparente residuelle de la voie C : plancher de bruit du capteur'
        WHEN 'c_current'    THEN 'Courant residuel de la voie C : plancher de sensibilite de la pince'
        WHEN 'c_voltage'    THEN 'Tension mesuree sur la voie C (meme conducteur que A : monophase)'
        WHEN 'c_pf'         THEN 'Facteur de puissance de la voie C : indefini sans courant (zero)'
        WHEN 'c_freq'       THEN 'Frequence du reseau mesuree sur la voie C (valide : mesuree sur la tension)'
        WHEN 'n_current'    THEN 'Courant de neutre CALCULE sous hypothese triphasee 120 deg : sans signification en monophase'
        WHEN 'rssi'         THEN 'Puissance du signal Wi-Fi recu par le Shelly : sante du lien radio de la collecte'
    END,
    CASE WHEN r.variable_name ~ 'aprt_power$' THEN 'VA'
         WHEN r.variable_name ~ 'act_power$'  THEN 'W'
         WHEN r.variable_name ~ 'current$'    THEN 'A'
         WHEN r.variable_name ~ 'voltage$'    THEN 'V'
         WHEN r.variable_name ~ 'pf$'         THEN 'sans unite'
         WHEN r.variable_name ~ 'freq$'       THEN 'Hz'
         WHEN r.variable_name = 'rssi'        THEN 'dB' END,
    CASE WHEN r.variable_name = 'n_current'   THEN NULL
         WHEN r.variable_name ~ 'act_power$'  THEN numrange(-100, 14500)
         WHEN r.variable_name ~ 'aprt_power$' THEN numrange(0, 14500)
         WHEN r.variable_name ~ 'current$'    THEN numrange(0, 63)
         WHEN r.variable_name ~ 'voltage$'    THEN numrange(80, 280)
         WHEN r.variable_name ~ 'pf$'         THEN numrange(-1, 1)
         WHEN r.variable_name ~ 'freq$'       THEN numrange(45, 55)
         WHEN r.variable_name = 'rssi'        THEN numrange(-100, -20) END,
    CASE WHEN r.variable_name = 'n_current'   THEN 'Non applicable (monophase)'
         WHEN r.variable_name ~ 'voltage$'    THEN 'Plausibilite capteur ; conformite fourniture 230 V +/-10 pct (207-253 V) a confirmer contractuellement'
         WHEN r.variable_name ~ 'pf$'         THEN 'Definition physique du ratio'
         WHEN r.variable_name ~ 'freq$'       THEN 'Plage plausible reseau 50 Hz'
         WHEN r.variable_name = 'rssi'        THEN 'Plage physique Wi-Fi'
         ELSE 'Calibre TC 63 A x 230 V nominal' END,
    CASE WHEN r.variable_name = 'n_current' THEN 'sans_signification'
         ELSE 'mesuree' END,
    CASE WHEN r.variable_name = 'rssi'      THEN 'exploitation_dispositif'
         WHEN r.variable_name = 'n_current' THEN 'temoin'
         WHEN r.variable_name = 'a_current' THEN 'securite'
         WHEN r.variable_name IN ('a_voltage','a_freq','b_voltage','b_freq',
                                  'c_voltage','c_freq')
                                            THEN 'qualite_fourniture'
         WHEN left(r.variable_name, 2) = 'a_' THEN 'mesure_consommation'
         WHEN left(r.variable_name, 2) = 'b_' THEN 'sous_comptage'
         ELSE 'temoin' END,
    CASE WHEN r.variable_name = 'n_current' THEN 'EXCLURE de toute analyse : hypothese triphasee sans objet ici'
         WHEN r.variable_name = 'rssi'      THEN 'Donnee du DISPOSITIF, pas du menage : ne jamais meler aux consommations ; divergence 1 dB entre methodes normale (2 instants)'
         WHEN r.variable_name ~ 'pf$'       THEN 'Inclut la distorsion : l ecart avec un cos phi reconstruit des energies chiffre les harmoniques'
         WHEN r.variable_name ~ 'voltage$'  THEN 'Meme conducteur sur les 3 voies (monophase) : redondance = preuve, pas information'
         WHEN left(r.variable_name, 2) = 'a_' THEN 'Voie A = TOTAL du menage (pince en sortie du differentiel)'
         WHEN left(r.variable_name, 2) = 'b_' THEN 'Partie INCLUSE dans A : ne JAMAIS additionner a A ; A - B = le reste'
         ELSE 'Voie sans charge : sert de reference de bruit du capteur' END
FROM shelly.p1_variable_registry r
ON CONFLICT (variable_id) DO UPDATE SET
    grandeur = EXCLUDED.grandeur, definition_fr = EXCLUDED.definition_fr,
    unite = EXCLUDED.unite, plage_plausible = EXCLUDED.plage_plausible,
    source_seuil = EXCLUDED.source_seuil, nature = EXCLUDED.nature,
    role_metier = EXCLUDED.role_metier, regle_usage = EXCLUDED.regle_usage;

CREATE OR REPLACE VIEW shelly.p1_correspondance_40_20 AS
SELECT r.variable_name AS grandeur,
       COUNT(*)        AS nb_chemins,
       STRING_AGG(r.rpc_method || ' -> ' || r.json_path, ' | '
                  ORDER BY r.rpc_method) AS chemins,
       CASE WHEN r.variable_name = 'rssi'
            THEN 'divergence marginale toleree (2 instants de mesure)'
            ELSE 'coincidence exigee a chaque cycle' END AS regle_croisement
FROM shelly.p1_variable_registry r
GROUP BY r.variable_name;

COMMENT ON VIEW shelly.p1_correspondance_40_20 IS
'Sous-livrable 1.2 : les 40 variables = 20 grandeurs x 2 methodes RPC.
Base du controle croise de l etape 5.';
