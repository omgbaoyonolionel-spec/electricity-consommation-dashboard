# Collecteur Tapo → PostgreSQL

Récupère automatiquement la consommation de vos prises TP-Link Tapo
(P110/P115...) directement en local (pas besoin de l'appli) et la stocke
dans PostgreSQL.

## Architecture

Le code est organisé en couches, pour isoler la logique métier des détails
techniques et faciliter l'ajout futur de nouveaux cas d'usage (agrégations,
alertes, export, dashboard...) :

```
src/
├── domain/                      # Cœur métier — zéro dépendance externe
│   ├── models.py                #   Device, DeviceReading (objets purs)
│   └── ports.py                 #   Interfaces : DeviceClientPort, ReadingRepositoryPort
├── infrastructure/              # Implémentations techniques concrètes
│   ├── config.py                #   Chargement de la config (variables d'env)
│   ├── tapo_client.py           #   Implémente DeviceClientPort avec la lib `tapo`
│   └── postgres_repository.py   #   Implémente ReadingRepositoryPort avec `asyncpg`
├── application/                 # Cas d'usage — orchestrent via les ports uniquement
│   └── collect_readings.py      #   CollectReadingsUseCase (collecte + sauvegarde)
└── main.py                      # Point de composition : assemble tout et lance
```

**Règle de dépendance** : `domain` ne dépend de rien ; `application` ne
dépend que de `domain` (jamais de `tapo` ou `asyncpg` directement) ;
`infrastructure` implémente les ports de `domain` ; `main.py` est le seul
fichier autorisé à connaître toutes les couches en même temps.

### Ajouter un nouveau cas d'usage d'exploitation de la donnée

Exemple : calculer un résumé quotidien de consommation.

1. Créez `app/application/compute_daily_summary.py`, une classe qui prend
   en dépendance `ReadingRepositoryPort` (déjà doté d'une méthode
   `find_by_device` prête pour ce genre de besoin) et implémente sa logique
   dans une méthode `execute(...)`.
2. Créez un petit point d'entrée (un nouveau fichier à côté de `main.py`,
   ou une nouvelle commande dans `main.py`) qui instancie
   `PostgresReadingRepository` et appelle ce nouveau cas d'usage.
3. Aucune modification de `domain` ni de `infrastructure` n'est nécessaire
   tant que le besoin peut s'exprimer via les ports existants. S'il faut une
   nouvelle capacité (ex: une requête d'agrégation SQL spécifique), ajoutez
   une méthode au port concerné dans `domain/ports.py`, puis implémentez-la
   dans `infrastructure/postgres_repository.py`.

### Pydantic et Alembic

- **Pydantic** : `Device` et `DeviceReading` (`app/domain/models.py`) sont des
  modèles Pydantic (validation automatique, immuables, sérialisables en
  JSON). La configuration (`app/infrastructure/config.py`) utilise
  `pydantic-settings` pour valider les variables d'environnement au
  démarrage — une variable manquante ou une prise mal configurée est
  détectée immédiatement, avec un message clair.
- **Alembic** gère désormais le schéma de la base (dossier `alembic/`), à la
  place de l'ancien `schema.sql` appliqué une seule fois. Pour créer une
  nouvelle migration après avoir modifié le schéma :
  ```bash
  alembic revision -m "description du changement"
  ```
  Éditez le fichier généré dans `alembic/versions/` (fonctions `upgrade()` /
  `downgrade()`), puis appliquez avec `alembic upgrade head` (fait
  automatiquement par le service `migrate` au démarrage de Docker Compose).

## Méthode recommandée : tout via Docker (automatique et permanent)

Solution la plus simple pour que la collecte tourne en continu, sans rien
configurer côté système (pas de cron, pas de systemd) : deux conteneurs
(PostgreSQL + collecteur), tous deux redémarrés automatiquement par Docker
si la machine reboote ou si un conteneur plante.

### 1. Configurer

```bash
cp .env.example .env
```

Éditez `.env` :
- `TAPO_EMAIL` / `TAPO_PASSWORD` : identifiants de votre compte Tapo (uniquement
  utilisés pour l'authentification locale avec chaque prise, rien ne part vers
  internet ensuite).
- `TAPO_DEVICES` : liste `nom=ip` de vos prises, séparées par des virgules.
  Trouvez l'IP de chaque prise dans l'appli Tapo → sélectionnez la prise →
  icône d'édition → "Infos sur l'appareil", ou via la liste des clients
  connectés de votre box (cherchez le nom "Tapo_...").
  ⚠️ Attribuez une IP fixe à chaque prise dans votre routeur (réservation DHCP)
  pour que le collecteur continue de fonctionner après un redémarrage de la box.
- Laissez `PG_DSN` tel quel (`@postgres:...`), c'est le nom du service Docker.

Changez aussi le mot de passe PostgreSQL par défaut dans `docker-compose.yml`
et `.env` (`tapo_password`).

### 2. Lancer

```bash
docker compose up -d --build
```

Cela démarre PostgreSQL, applique automatiquement les migrations Alembic
(service `migrate`, s'exécute une fois puis s'arrête), puis démarre le
collecteur, qui interroge vos prises toutes les 5 minutes (modifiable dans
`docker-compose.yml`, argument `--loop 300`, en secondes) et écrit dans la
base.

### 3. Vérifier que ça tourne

```bash
docker compose logs -f collector
```

Une ligne par prise doit apparaître à chaque cycle. Pour consulter les
données :

```bash
docker exec -it tapo_postgres psql -U tapo -d tapo -c "SELECT * FROM tapo_readings ORDER BY timestamp DESC LIMIT 10;"
```

### 4. Ça redémarre tout seul après un reboot de la machine ?

Oui, tant que le démon Docker démarre au boot (comportement par défaut sur la
plupart des installations Linux et Docker Desktop). Vérifiez avec :

```bash
sudo systemctl is-enabled docker   # doit répondre "enabled"
```

## Développement / exécution locale sans Docker

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
export $(cat .env | xargs)   # ou chargez .env autrement
alembic upgrade head          # applique les migrations sur votre Postgres local
python -m app.main            # une seule collecte
python -m app.main --loop 300 # collecte en boucle
```

## Notes

- `current_power_mw` est en milliwatts, `today_energy_wh` et `month_energy_wh`
  en watt-heures (champs renvoyés nativement par la prise).
- Si une prise change d'IP (pas de réservation DHCP), le collecteur échouera
  pour cette prise seulement — pensez à fixer les IP.
- Pour visualiser les courbes, vous pouvez brancher Grafana sur cette base
  PostgreSQL, ou interroger directement via psql/DBeaver.