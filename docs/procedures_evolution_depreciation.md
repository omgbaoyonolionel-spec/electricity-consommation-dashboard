# PROCEDURE D EVOLUTION (ajout d une source) - Phase 4.3 - v1.0.0
# Les 9 etapes du meta-prompt, outillees par l existant du pilote.

etapes:
  1: identifier la RPC/variable (Shelly.ListMethods deja inventorie : 129 methodes)
  2: nommer selon la nomenclature CANAL_GRANDEUR_STATUT_AGREGATION (0.4)
  3: classer domaine/nature/frequence/mode (INSERT dans shelly.referentiel_variables)
  4: qualifier par les 6 tests (INSERT dans shelly.qualification_tests)
  5: valider sur jeu de test (PG replique - methode etape 2)
  6: ajouter au dictionnaire (regenerer dictionnaire_donnees.yaml depuis la base)
  7: integrer au pipeline (collecteur + registre P1 si flux continu)
  8: documenter (lignage + catalogue_flux + commit-tag)
  9: verifier la non-regression (recettes des phases 1-3 rejouees : comptes inchanges + N nouvelles)

cas_application_1: SYS_temp_inst (temperature interne, 54.8 C au 1er releve)
  statut: etapes 1-4 FAITES (referentiel ligne 67, plage -40..85, alerte P3 posee)
  reste: 5-9 -> 41e variable du collecteur P1 (1 appel Temperature.GetStatus/cycle)

---
# PROCEDURE DE DEPRECIATION (retrait d une source) - Phase 4.4 - v1.0.0

etapes:
  1: identifier la source obsolete et documenter les motifs chiffres
  2: verifier les dependances (grep dans dashboards, scripts, vues)
  3: transition >= 30 jours, source marquee DEPRECIE dans le catalogue
  4: journaliser l utilisation residuelle pendant la transition
  5: annoncer (README + commit dedie)
  6: retirer (arret du collecteur, table conservee en archive - jamais de DROP de Bronze)
  7: mettre a jour catalogue_flux + lignage + dictionnaire
  8: verifier la non-regression (recettes rejouees)

cas_application_1: FLUX_99_readings_1s_heritage (shelly_readings + shelly_collector)
  motifs_chiffres: 856 reculs de compteur (flux fantome 10.24.38.200), redondance
    avec FLUX_01 P1, source de l erreur 5.7 GWh d un script tiers
  statut: etape 1 FAITE (catalogue : DEPRECIE_CANDIDAT) ; etape 2 = verifier
    dashboard_shelly.py et les scripts d export avant l arret ; fenetre de
    transition proposee : 05/09 -> 05/10/2026 ; etape 6 = arret de
    shelly_collector (divise par 2 la charge sur le serveur HTTP de l appareil -
    benefice documente lors de l etouffement du 04/09)
