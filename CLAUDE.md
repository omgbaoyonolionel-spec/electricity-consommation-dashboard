# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A collector that polls TP-Link Tapo smart plugs (P110/P115...) directly over the local network (no cloud/app dependency) and writes power-consumption readings into PostgreSQL. French is the working language for docstrings, log messages, and commit content — match it when editing existing files.

## History: this repo was mid-refactor

It was restructured from a top-level `app/` package (with Alembic migrations) to `src/` + a plain `schema.sql`. That migration has since been completed: imports across `src/` and root `main.py` reference `src.*`, `dockerfile`/`docker-compose.yaml` copy/run `src/` + `main.py` (not `app/`), and `schema.sql` creates `tapo_readings` and is mounted into the postgres container's `docker-entrypoint-initdb.d`. `PostgresReadingRepository` also got a `create(dsn)` classmethod it was missing, and a `save()` bug (undefined `_INSERT_SQL` name, `self.pool` typo) was fixed. If you see `app.` imports or Alembic references reappear anywhere, that's regressed — bring it back to the `src/` + `schema.sql` shape described below rather than reintroducing Alembic.

## Architecture

Layered/hexagonal design (see `README.md` for the full rationale, in French) so business logic stays isolated from technical details and new use cases (aggregations, alerts, export, dashboard...) are cheap to add:

```
domain/           # Core business logic — meant to have zero external deps, though
                   #   Device/DeviceReading are Pydantic models (validation + JSON
                   #   serialization traded for strict "zero dependency")
  models.py        Device, DeviceReading
  ports.py         DeviceClientPort, ReadingRepositoryPort (abstract interfaces)
infrastructure/   # Concrete technical implementations
  config.py        Settings (pydantic-settings, loads/validates .env)
  tapo_client.py    TapoDeviceClient — implements DeviceClientPort via the `tapo` lib
  postgres_repository.py  PostgresReadingRepository — implements ReadingRepositoryPort via asyncpg
application/      # Use cases — orchestrate only through domain ports, never
                   #   import tapo or asyncpg directly
  collect_readings.py  CollectReadingsUseCase (collect + persist, per-device error isolation)
main.py           # Composition root — the only file allowed to know about all layers at once
```

**Dependency rule**: `domain` depends on nothing external (aside from the Pydantic tradeoff above). `application` depends only on `domain` — never directly on `tapo` or `asyncpg`. `infrastructure` implements `domain`'s ports. `main.py` wires concrete infrastructure implementations into use cases.

### Adding a new use case that reads existing data

Example given in the README: a daily consumption summary.

1. Add `application/compute_daily_summary.py`: a class taking `ReadingRepositoryPort` as a dependency (it already exposes `find_by_device`) with an `execute(...)` method.
2. Add a small entry point (new script, or a new subcommand in `main.py`) that constructs `PostgresReadingRepository` and calls the new use case.
3. Don't touch `domain`/`infrastructure` unless the existing ports can't express the need — if a new capability is required (e.g. a specific aggregation query), add a method to the relevant port in `domain/ports.py` first, then implement it in `infrastructure/postgres_repository.py`.

### Config

`infrastructure/config.py`'s `Settings` (pydantic-settings) loads and validates env vars at startup — a missing var or empty `TAPO_DEVICES` fails fast with a clear message rather than failing later mid-collection. `TAPO_DEVICES` is a single env var of comma-separated `name=ip` pairs, parsed into a `dict[str, str]` via the `devices` property.

## Running

Via Docker (intended production path — continuous collection, auto-restart on reboot/crash; postgres applies `schema.sql` automatically on first start via `docker-entrypoint-initdb.d`):
```bash
cp .env.example .env   # then fill in TAPO_EMAIL, TAPO_PASSWORD, TAPO_DEVICES
docker compose up -d --build
docker compose logs -f collector
```

Local/dev without Docker (run from the repo root — `main.py` and `src/` must both be on the CWD for the `src.*` imports to resolve):
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
export $(cat .env | xargs)
python main.py            # single collection pass
python main.py --loop 300 # loop every N seconds
```

Query stored readings directly:
```bash
docker exec -it tapo_postgres psql -U tapo -d tapo -c "SELECT * FROM tapo_readings ORDER BY timestamp DESC LIMIT 10;"
```

No test suite, linter, or type-checker is currently configured in this repo (no `pytest`, `ruff`, `mypy`, or `pyproject.toml`).

## Domain notes

- `current_power_mw` is in milliwatts; `today_energy_wh` and `month_energy_wh` are in watt-hours — these are the units the Tapo device firmware returns natively, don't convert them elsewhere.
- `CollectReadingsUseCase.execute` isolates failures per device (e.g. a plug that changed IP without a DHCP reservation) so one unreachable plug doesn't block collection for the others — preserve that behavior when touching this use case.
- Tapo credentials (`TAPO_EMAIL`/`TAPO_PASSWORD`) are only used for local authentication with each plug; nothing is sent to the TP-Link cloud after that.
