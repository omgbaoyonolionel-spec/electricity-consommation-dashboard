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
└── application/                 # Cas d'usage — orchestrent via les ports uniquement
    └── collect_readings.py      #   CollectReadingsUseCase (collecte + sauvegarde)
main.py                          # Point de composition : assemble tout et lance
schema.sql                       # Schéma PostgreSQL, appliqué automatiquement au démarrage du conteneur postgres
```

**Règle de dépendance** : `domain` ne dépend de rien ; `application` ne
dépend que de `domain` (jamais de `tapo` ou `asyncpg` directement) ;
`infrastructure` implémente les ports de `domain` ; `main.py` est le seul
fichier autorisé à connaître toutes les couches en même temps.

### Ajouter un nouveau cas d'usage d'exploitation de la donnée

Exemple : calculer un résumé quotidien de consommation.

1. Créez `src/application/compute_daily_summary.py`, une classe qui prend
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

### Pydantic

`Device` et `DeviceReading` (`src/domain/models.py`) sont des modèles
Pydantic (validation automatique, immuables, sérialisables en JSON). La
configuration (`src/infrastructure/config.py`) utilise `pydantic-settings`
pour valider les variables d'environnement au démarrage — une variable
manquante ou une prise mal configurée est détectée immédiatement, avec un
message clair.

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

Cela démarre PostgreSQL (schéma appliqué automatiquement via `schema.sql`)
puis le collecteur, qui interroge vos prises toutes les 5 minutes
(modifiable dans `docker-compose.yml`, argument `--loop 300`, en secondes)
et écrit dans la base.

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
python main.py                # une seule collecte
python main.py --loop 300     # collecte en boucle
```

> ⚠️ Sous Windows, la commande `export $(cat .env | xargs)` ne fonctionne pas
> (Git Bash la gère mal si des valeurs contiennent des espaces, et PowerShell ne
> la connaît pas). Préférez la méthode `uv` ci-dessous.

Avec [uv](https://docs.astral.sh/uv/) à la place de `venv`/`pip` :

```bash
uv venv
uv pip install -r requirements.txt
.venv\Scripts\activate        # Windows — sous Linux/macOS : source .venv/bin/activate
python main.py --loop 300
```

## Commandes utiles

```bash
# Démarrer / reconstruire les conteneurs
docker compose up -d --build

# État des conteneurs (démarré ? healthy ?)
docker compose ps

# Suivre les logs du collecteur (Ctrl+C pour quitter)
docker compose logs -f collector

# Redémarrer le collecteur avec la config .env à jour (après avoir édité .env)
docker compose up -d --force-recreate collector

# Tout arrêter (les données restent dans le volume tapo_pgdata)
docker compose down

# Requête SQL ponctuelle sans ouvrir de shell
docker exec tapo_postgres psql -U tapo -d tapo -c "SELECT * FROM tapo_readings ORDER BY timestamp DESC LIMIT 10;"

# Ouvrir un shell psql interactif
docker exec -it tapo_postgres psql -U tapo -d tapo
```

## Visualiser les données

### Ligne de commande

```bash
docker exec tapo_postgres psql -U tapo -d tapo -c "SELECT * FROM tapo_readings ORDER BY timestamp DESC LIMIT 10;"
```

### pgAdmin (en local)

Le conteneur `postgres` publie son port sur la machine hôte (`localhost:5432`),
donc pgAdmin (ou DBeaver, TablePlus...) s'y connecte directement, sans rien
configurer côté Docker :

1. Vérifiez que le conteneur tourne : `docker compose ps` doit montrer
   `tapo_postgres` en état `healthy`.
2. Dans pgAdmin : clic droit sur **Servers** → **Register → Server...**
3. Onglet **General** : donnez-lui un nom (ex. `tapo`).
4. Onglet **Connection** :
   - **Host name/address** : `localhost` (uniquement le host, sans le port)
   - **Port** : `5432`
   - **Maintenance database** : `tapo`
   - **Username** : `tapo`
   - **Password** : la valeur de `POSTGRES_PASSWORD` dans `docker-compose.yaml`
     (= `PG_DSN`/`PGADMIN_PG_PASSWORD` dans `.env`)
   - Activez **Save password?** puis **Save**.
5. Dans l'arborescence : **Servers → tapo → Databases → tapo → Schemas →
   public → Tables → tapo_readings**, clic droit → **View/Edit Data → All
   Rows** pour voir le contenu, ou l'icône éclair (**Query Tool**) pour taper
   du SQL directement.

## Notes

- `current_power_mw` est en milliwatts, `today_energy_wh` et `month_energy_wh`
  en watt-heures (champs renvoyés nativement par la prise).
- Si une prise change d'IP (pas de réservation DHCP), le collecteur échouera
  pour cette prise seulement — pensez à fixer les IP.
- Pour visualiser les données : voir la section [Visualiser les données](#visualiser-les-données)
  ci-dessus (psql ou pgAdmin). Pour de vrais graphiques, vous pouvez aussi
  brancher Grafana sur cette base PostgreSQL.