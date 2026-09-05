-- PHASE 1 (meta-prompt V3.0) : classification domaine / nature / frequence. v1.1.0
ALTER TABLE shelly.referentiel_variables
  ADD COLUMN IF NOT EXISTS domaine TEXT,
  ADD COLUMN IF NOT EXISTS nature TEXT,
  ADD COLUMN IF NOT EXISTS frequence_emission TEXT;

-- 1.1 DOMAINE physique
UPDATE shelly.referentiel_variables SET domaine = CASE
  WHEN nom_normalise LIKE 'SYS_temp%' THEN 'thermique'
  WHEN nom_normalise IN ('SYS_rssi_inst','SYS_ip_courante') THEN 'reseau'
  WHEN nom_normalise = 'TS_utc_1m' THEN 'temporel'
  WHEN nom_normalise LIKE 'SYS_%' OR nom_normalise IN ('N_current_inst') AND classe='systeme' THEN 'systeme'
  WHEN classe='qualite' THEN 'qualite'
  ELSE 'electrique' END;
UPDATE shelly.referentiel_variables SET domaine='systeme'
 WHERE classe='systeme' AND domaine NOT IN ('thermique','reseau','temporel');
UPDATE shelly.referentiel_variables SET domaine='qualite' WHERE classe='qualite';

-- 1.2 NATURE (amendements a et b appliques)
UPDATE shelly.referentiel_variables SET nature = CASE
  WHEN licence_usage='interdit' THEN 'DERIVEE_INTERDITE'
  WHEN nom_normalise ~ '_vie$' THEN 'CUMULATIVE'
  WHEN nom_normalise ~ '(pf|aprt)_inst$' THEN 'CALCULEE'
  WHEN nom_normalise ~ '_(max|min|avg)_1m$' THEN 'DERIVEE'
  WHEN nom_normalise ~ 'energy.*_1m$' THEN 'DERIVEE'
  WHEN classe='native' THEN 'NATIVE'
  WHEN classe='qualite' THEN 'INDICATEUR'
  ELSE 'SYSTEME' END;

-- 1.3 FREQUENCE d emission
UPDATE shelly.referentiel_variables SET frequence_emission = CASE
  WHEN nom_normalise = 'SYS_ip_courante' THEN 'evenementielle'
  WHEN nom_normalise ~ '_inst$' THEN 'instantanee_~1s_polling'
  WHEN nom_normalise ~ '_1m$' THEN 'synthetique_60s_memoire'
  WHEN nom_normalise ~ '_vie$' THEN 'compteur_a_la_demande'
  ELSE 'systeme_a_la_demande' END;

COMMENT ON COLUMN shelly.referentiel_variables.nature IS
'NATIVE=mesuree par le capteur ; CALCULEE=calculee PAR L APPAREIL (pf=P/S, S=UxI) ;
CUMULATIVE=compteur a vie strictement croissant (test CROISSANCE applicable) ;
DERIVEE=transformation sur fenetre (min/max/avg, integration energie-minute :
peut decroitre, NE JAMAIS traiter en compteur) ; DERIVEE_INTERDITE=somme
constructeur double-comptant en monophase ; SYSTEME ; INDICATEUR.';
