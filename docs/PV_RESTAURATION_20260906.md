# PROCES-VERBAL DE RESTAURATION REELLE - Porte G7 - 06-07/09/2026
Sauvegarde : tapo_baseline_20260906.dump (74,4 Mo, pg_dump -Fc, PostgreSQL 16.15)
SHA-256 scelle et RE-VERIFIE au PV : C9A950C59D26938F8B126EDFF1F4C3A74BC40ADF8C630D95A98606A5E21E8F76
Environnement : conteneur isole restauration_test (image de production), jamais la prod.
Commande : pg_restore -U tapo -d tapo --no-owner /tmp/b.dump
RTO MESURE : 138 s. RPO OBSERVE : ~1-2 min (dump ~23:31 locale, derniere minute 23:30).
RPO GARANTI : indefini (dump ponctuel) -> automatisation quotidienne au plan sentinelle.
Controles : schema 442 colonnes / 32 tables identiques prod-restauree ; 8407 minutes
restaurees (31/08 16:33 UTC -> 06/09 22:30 UTC) ; quarantaine 34/34 ; referentiel 67/67 ;
109692 cycles P1 ; energie A 81,130 kWh au wattheure ; ecart prod 20 min / 0,135 kWh
POSTERIEUR au dump (explique, consigne) ; gold.bilan_journalier 7/7 jours conformes ;
re-restore de controle dans tapo_verif : zero erreur (grep -ci error = 0).
Verdict : RESTAURATION VALIDEE - le plafond 8,5 (absence de restauration reelle) TOMBE.
Reserves : dump non automatise (RPO garanti absent) ; copie hors machine absente (3-2-1).
