# 00_CONTEXTE_ET_HYPOTHESES - Porte G0 - 06/09/2026 - commit 86fcbb5
Environnement : Windows 11 (26200), Docker 29.4.1, Compose v5.1.3, Python 3.14.0,
PostgreSQL 16.15 Alpine (conteneur tapo_postgres). Fuseau Africa/Douala, stockage UTC.
Appareil : SPEM-003CEBEU63 gen2, a4f00fccaf68, fw 1.4.0 (2.0.0 dispo - decision differee,
OTA en liste noire). Monophase. A=reference foyer, B sous A (jamais A+B), C=temoin
(retour continu 0.0704 kWh/6640 min : FIELD_VERIFICATION_REQUIRED, pince a verifier).
P1 = flux primaire 1 s (2 methodes croisees, payloads scelles). Memoire minute
EMData.GetRecords = source de reference, INDEPENDANTE du flux 1 s (60 j de profondeur).
FLUX_99 (shelly_readings) DEPRECIE (856 reculs, flux fantome) - exclu de la cible.
Terminologie P1 : conforme a la definition du mandat, pas de table d equivalence requise.
Corpus certifie : 6640x55 (01-05/09), 8 tests bloquants, runs A/B au hash semantique,
CLOSED_SILVER_GOLD_BLOCKED (7 decisions en attente, la 7e liee a la pince C).
