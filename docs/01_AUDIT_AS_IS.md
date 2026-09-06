# 01_AUDIT_AS_IS - Porte G0 - 06/09/2026 - commit 86fcbb5
## Architecture reelle
Shelly --(HTTP RPC, IP hotspot mouvante, suffixe .134 stable)--> 3 collecteurs Docker
(shelly_p1 1s/2 methodes ; shelly_history minute/EMData ; shelly_collector DEPRECIE)
--> PostgreSQL 16 (zones bronze/silver/quarantaine/gold + monitoring) --> exports scelles.
Automates : restart unless-stopped 6/6 (verifie par inspect), docteur IP (tache 5 min,
en ronde depuis 06/09 02:41), powercfg total (ac+dc+capot). AUCUN spool Edge 1 s.
## Mesures baseline (semaine 31/08-06/09)
Cadence P1 ~57 cycles/min ; derive horloge lente ~20 s (VM) ; 10 absences canoniques
(560 min sur 01-05/09 + 4 min le 06/09, toutes datees) ; latence ingestion P50 8529 s
sur fenetre a pannes (P99 104344 s) ; MTTR panne IP : 24 h avant docteur, <=5 min apres ;
34 decisions de quarantaine signees ; reconciliation 6/6 jours <=2 pct (manuelle).
## SPOF et actions manuelles cachees
1 PC portable (hote unique), 1 hotspot (8 sous-reseaux/7 j), 1 humain (Lio) ;
reconciliation, tests qualite et alertes NON branches (sentinelle absente) ;
auth_en=false (P0) ; credentials en clair dans .env LOCAL (verifie non suivi, absent de l historique, exclu par .gitignore:151 - migration Docker secrets en G8) ; aucune CI ;
aucune sauvegarde restauree ; pas d outil de migration ; git jamais pousse.
## Score initial (grille 100 pts, sans arrondi haut)
Dictionnaire 4/10 ; Reconciliation 4/15 ; Episodes-alertes 2/10 ; SLI-SLO 2/10 ;
Tampon-resilience 3/15 ; Tests-CI 2/12 ; Sauvegardes 1/10 (dump baseline cree, jamais
restaure) ; Secrets-migrations 1/8 ; Multi-menages 0/10 (BLOCKED materiel).
TOTAL AS-IS : 19/100 (~1.9/10). Plafonds actifs : 8.0 (reconciliation manuelle, pas de
tampon), 8.5 (CI, restauration), 8.8 (mono-menage). Chemin critique vers >90 :
sentinelle-reconciliateur -> spool Edge + crash-tests -> CI -> restauration prouvee ->
SetAuth + secrets -> 3 menages x 7 jours (G9, materiel a acquerir).
