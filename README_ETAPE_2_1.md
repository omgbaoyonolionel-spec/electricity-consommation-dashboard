# Étape 2.1 — Contrat P1 canonique

## Résultat

L'outil crée sans écrasement :

- `catalogue_p1_v2.0.0.csv` : dictionnaire canonique ;
- `catalogue_p1_v2.0.0.manifest.json` : empreintes et approbation ;
- `catalogue_p1_v2.0.0.rapport.json` : résultats des contrôles.

Chaque exécution est conservée dans un sous-dossier horodaté distinct. Un
brouillon antérieur n'est donc jamais écrasé lors de l'approbation.

Il conserve uniquement `Shelly.GetStatus`, reclasse les trois totaux momentanés,
impose une fréquence d'une seconde et attend 23 grandeurs canoniques. Si le nombre
réel est différent, il s'arrête : la différence doit être examinée, jamais masquée.

## Installation

Copier les trois fichiers dans :

`C:\Users\omgba.oyono.lionel\Desktop\CAPACITES\electricity-consommation-dashboard`

## 1. Génération en brouillon

```powershell
.\executer_etape_2_1.ps1
```

## 2. Génération approuvée

Ne lancer cette commande qu'après décision formelle de la direction :

```powershell
.\executer_etape_2_1.ps1 `
  -ApprovedBy "Nom de l'approbateur" `
  -ApprovalReference "DECISION-DIRECTION-2026-001"
```

## 3. Enregistrement et comparaison PostgreSQL

`psycopg2-binary` doit être installé dans l'environnement Python utilisé.

```powershell
.\executer_etape_2_1.ps1 `
  -ApprovedBy "Nom de l'approbateur" `
  -ApprovalReference "DECISION-DIRECTION-2026-001" `
  -RegisterDatabase `
  -AuditDatabase
```

L'audit PostgreSQL reste en échec tant que le collecteur actif ne correspond pas
au contrat : même nombre de variables, un seul payload RPC, aucune variable
manquante et version du collecteur 2.x.

## Sécurité

Le mot de passe PostgreSQL n'est écrit dans aucun fichier. Le script PowerShell
lit temporairement le `PG_DSN` déjà configuré dans le conteneur, puis efface la
variable de son propre processus.

L'empreinte SHA-256 démontre l'intégrité du fichier. Elle ne constitue pas, à
elle seule, une signature ou une approbation humaine.
