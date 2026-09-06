#!/usr/bin/env python3
r"""Collecteur P1 des 40 variables instantanées du catalogue Shelly.

Le programme :
- charge le dernier 03_04_catalogue_variables_classees.csv ;
- exige exactement 40 variables de catégorie « instantanée » ;
- interroge Shelly.GetStatus et Shelly.GetComponents toutes les secondes ;
- conserve les réponses RPC brutes et une observation par variable dans PostgreSQL ;
- inscrit explicitement les variables absentes, sans les remplacer par zéro.

Exécution Docker attendue : python shelly_p1_collector.py
Test unique :             python shelly_p1_collector.py --once
Autotest sans réseau/DB : python shelly_p1_collector.py --self-test
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import logging
import math
import os
import signal
import socket
import sys
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


VERSION = "1.0.0"
EXPECTED_VARIABLES = 40
READ_ONLY_METHODS = ("Shelly.GetStatus", "Shelly.GetComponents")
STOP_REQUESTED = False
LOG = logging.getLogger("shelly-p1")
MISSING = object()


DDL = """
CREATE SCHEMA IF NOT EXISTS shelly;

CREATE TABLE IF NOT EXISTS shelly.p1_variable_registry (
    variable_id          text PRIMARY KEY,
    device_id            text NOT NULL,
    firmware_version     text NOT NULL,
    rpc_method           text NOT NULL,
    component_key        text NOT NULL DEFAULT '',
    section_name         text NOT NULL,
    json_path            text NOT NULL,
    variable_name        text NOT NULL,
    declared_data_type   text,
    category             text NOT NULL CHECK (category = 'instantanée'),
    priority_level       text NOT NULL CHECK (priority_level = 'P1'),
    frequency_seconds    integer NOT NULL CHECK (frequency_seconds = 1),
    classification_rule  text,
    catalog_source       text NOT NULL,
    enabled              boolean NOT NULL DEFAULT true,
    first_registered_at  timestamptz NOT NULL DEFAULT now(),
    last_registered_at   timestamptz NOT NULL DEFAULT now(),
    UNIQUE (device_id, firmware_version, rpc_method, component_key, section_name, json_path)
);

CREATE TABLE IF NOT EXISTS shelly.p1_collection_cycle (
    cycle_id             uuid PRIMARY KEY,
    device_id            text NOT NULL,
    scheduled_at         timestamptz NOT NULL,
    started_at           timestamptz NOT NULL,
    completed_at         timestamptz,
    device_timestamp     timestamptz,
    expected_variables   integer NOT NULL,
    present_variables    integer NOT NULL DEFAULT 0,
    missing_variables    integer NOT NULL DEFAULT 0,
    raw_payload_count    integer NOT NULL DEFAULT 0,
    duration_ms          integer,
    cycle_status         text NOT NULL,
    errors_json          jsonb NOT NULL DEFAULT '[]'::jsonb,
    collector_version    text NOT NULL,
    collector_host       text NOT NULL,
    inserted_at          timestamptz NOT NULL DEFAULT now(),
    UNIQUE (device_id, scheduled_at)
);

CREATE TABLE IF NOT EXISTS shelly.p1_raw_rpc (
    raw_event_id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    cycle_id             uuid NOT NULL REFERENCES shelly.p1_collection_cycle(cycle_id) ON DELETE CASCADE,
    device_id            text NOT NULL,
    rpc_method           text NOT NULL,
    requested_at         timestamptz NOT NULL,
    received_at          timestamptz NOT NULL,
    duration_ms          integer NOT NULL,
    payload              jsonb NOT NULL,
    payload_sha256       char(64) NOT NULL,
    collector_version    text NOT NULL,
    UNIQUE (cycle_id, rpc_method)
);

CREATE TABLE IF NOT EXISTS shelly.p1_instantaneous_observation (
    cycle_id             uuid NOT NULL REFERENCES shelly.p1_collection_cycle(cycle_id) ON DELETE CASCADE,
    variable_id          text NOT NULL REFERENCES shelly.p1_variable_registry(variable_id),
    device_id            text NOT NULL,
    component_key        text NOT NULL DEFAULT '',
    rpc_method           text NOT NULL,
    json_path            text NOT NULL,
    observed_at          timestamptz NOT NULL,
    received_at          timestamptz NOT NULL,
    device_timestamp     timestamptz,
    clock_offset_ms      integer,
    is_present           boolean NOT NULL,
    numeric_value        double precision,
    text_value           text,
    boolean_value        boolean,
    json_value           jsonb,
    value_type           text,
    quality_status       text NOT NULL,
    quality_flags        text[] NOT NULL DEFAULT '{}',
    raw_event_id         bigint REFERENCES shelly.p1_raw_rpc(raw_event_id),
    inserted_at          timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (cycle_id, variable_id),
    CHECK (
        (NOT is_present AND num_nonnulls(numeric_value, text_value, boolean_value, json_value) = 0)
        OR
        (is_present AND num_nonnulls(numeric_value, text_value, boolean_value, json_value) = 1)
    )
);

CREATE INDEX IF NOT EXISTS ix_p1_observation_time
    ON shelly.p1_instantaneous_observation (device_id, observed_at DESC);
CREATE INDEX IF NOT EXISTS ix_p1_observation_variable_time
    ON shelly.p1_instantaneous_observation (variable_id, observed_at DESC);
CREATE INDEX IF NOT EXISTS ix_p1_missing
    ON shelly.p1_instantaneous_observation (observed_at DESC)
    WHERE NOT is_present;
CREATE INDEX IF NOT EXISTS ix_p1_raw_payload_gin
    ON shelly.p1_raw_rpc USING gin (payload);
"""


@dataclass(frozen=True)
class VariableSpec:
    variable_id: str
    rpc_method: str
    component_key: str
    section: str
    json_path: str
    variable_name: str
    data_type: str
    classification_rule: str


@dataclass
class RpcCapture:
    method: str
    requested_at: datetime
    received_at: datetime
    duration_ms: int
    envelope: dict[str, Any]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_z(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def stable_variable_id(device_id: str, firmware: str, row: dict[str, str]) -> str:
    identity = "|".join((device_id, firmware, row.get("source_rpc", ""),
                         row.get("composant", ""), row.get("section", ""),
                         row.get("chemin_json", "")))
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()[:32]


def find_latest_catalog(root: Path) -> Path:
    candidates = list(root.glob("**/03_04_catalogue_variables_classees.csv"))
    if not candidates:
        raise FileNotFoundError(f"Catalogue introuvable sous {root.resolve()}")
    return max(candidates, key=lambda p: p.stat().st_mtime)


def load_specs(path: Path, device_id: str, firmware: str) -> list[VariableSpec]:
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream, delimiter=";"))
    selected = [row for row in rows if row.get("categorie", "").strip().lower() == "instantanée"]
    if len(selected) != EXPECTED_VARIABLES:
        raise ValueError(
            f"Le catalogue contient {len(selected)} variables instantanées; {EXPECTED_VARIABLES} attendues."
        )
    specs = []
    seen = set()
    for row in selected:
        method = row.get("source_rpc", "").strip()
        if method not in READ_ONLY_METHODS:
            raise ValueError(f"Source RPC P1 non autorisée : {method!r}")
        spec = VariableSpec(
            variable_id=stable_variable_id(device_id, firmware, row),
            rpc_method=method,
            component_key=row.get("composant", "").strip(),
            section=row.get("section", "").strip(),
            json_path=row.get("chemin_json", "").strip(),
            variable_name=row.get("nom_variable", "").strip(),
            data_type=row.get("type_donnee", "").strip(),
            classification_rule=row.get("regle_appliquee", "").strip(),
        )
        key = (spec.rpc_method, spec.component_key, spec.section, spec.json_path)
        if key in seen:
            raise ValueError(f"Variable P1 dupliquée dans le catalogue : {key}")
        seen.add(key)
        specs.append(spec)
    return sorted(specs, key=lambda x: (x.rpc_method, x.component_key, x.json_path))


class ShellyClient:
    def __init__(self, host: str, timeout: float):
        self.url = f"http://{host}/rpc"
        self.timeout = timeout
        self.request_id = 0

    def call(self, method: str, params: dict[str, Any] | None = None) -> RpcCapture:
        if method not in READ_ONLY_METHODS:
            raise ValueError(f"Méthode RPC refusée : {method}")
        self.request_id += 1
        body = canonical_json({"id": self.request_id, "method": method, "params": params or {}}).encode()
        request = urllib.request.Request(
            self.url, data=body, method="POST",
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )
        requested = utc_now()
        started = time.monotonic_ns()
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                envelope = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:300]
            raise RuntimeError(f"{method}: HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"{method}: connexion impossible: {exc.reason}") from exc
        received = utc_now()
        duration = round((time.monotonic_ns() - started) / 1_000_000)
        if not isinstance(envelope, dict) or "result" not in envelope:
            raise RuntimeError(f"{method}: réponse RPC invalide")
        if envelope.get("error"):
            raise RuntimeError(f"{method}: {envelope['error']}")
        return RpcCapture(method, requested, received, duration, envelope)

    def components_status(self) -> RpcCapture:
        all_components: list[Any] = []
        raw_pages: list[dict[str, Any]] = []
        offset = 0
        requested = utc_now()
        started = time.monotonic_ns()
        received = requested
        cfg_rev = None
        total = None
        for _ in range(100):
            capture = self.call("Shelly.GetComponents", {"offset": offset, "include": ["status"]})
            received = capture.received_at
            result = capture.envelope["result"]
            page = result.get("components", [])
            raw_pages.append(capture.envelope)
            all_components.extend(page)
            cfg_rev = result.get("cfg_rev", cfg_rev)
            total = result.get("total", total)
            next_offset = int(result.get("offset", offset)) + len(page)
            if not page or (total is not None and next_offset >= int(total)):
                envelope = {"result": {"components": all_components, "cfg_rev": cfg_rev,
                                       "offset": 0, "total": total or len(all_components),
                                       "raw_pages": raw_pages}}
                return RpcCapture("Shelly.GetComponents", requested, received,
                                  round((time.monotonic_ns() - started) / 1_000_000), envelope)
            if next_offset <= offset:
                raise RuntimeError("Shelly.GetComponents: pagination sans progression")
            offset = next_offset
        raise RuntimeError("Shelly.GetComponents: plus de 100 pages")


def path_tokens(path: str) -> list[str]:
    clean = path.strip()
    if clean == "$":
        return []
    if clean.startswith("$."):
        clean = clean[2:]
    return [token for token in clean.split(".") if token]


def extract_path(value: Any, path: str) -> Any:
    current = value
    for token in path_tokens(path):
        array = token.endswith("[]")
        key = token[:-2] if array else token
        if not isinstance(current, dict) or key not in current:
            return MISSING
        current = current[key]
        if array:
            if not isinstance(current, list):
                return MISSING
            # Une structure répétée est conservée comme JSON dans une observation unique.
            return current
    return current


def component_result(capture: RpcCapture, component_key: str, section: str) -> Any:
    components = capture.envelope["result"].get("components", [])
    for component in components:
        if isinstance(component, dict) and str(component.get("key", "")) == component_key:
            return component.get(section, MISSING)
    return MISSING


def device_timestamp(captures: dict[str, RpcCapture]) -> datetime | None:
    status = captures.get("Shelly.GetStatus")
    if not status:
        return None
    epoch = status.envelope.get("result", {}).get("sys", {}).get("unixtime")
    try:
        return datetime.fromtimestamp(float(epoch), timezone.utc)
    except (TypeError, ValueError, OSError):
        return None


def typed_value(value: Any) -> tuple[Any, Any, Any, str | None, str]:
    if isinstance(value, bool):
        return None, None, value, None, "boolean"
    if isinstance(value, (int, float)):
        number = float(value)
        if not math.isfinite(number):
            raise ValueError("valeur numérique NaN ou infinie")
        return number, None, None, None, "number"
    if isinstance(value, str):
        return None, value, None, None, "string"
    return None, None, None, canonical_json(value), "null" if value is None else "json"


def database_dsn() -> str:
    if os.getenv("DATABASE_URL"):
        return os.environ["DATABASE_URL"]
    host = os.getenv("PGHOST", os.getenv("POSTGRES_HOST", "postgres"))
    port = os.getenv("PGPORT", os.getenv("POSTGRES_PORT", "5432"))
    dbname = os.getenv("PGDATABASE", os.getenv("POSTGRES_DB", "postgres"))
    user = os.getenv("PGUSER", os.getenv("POSTGRES_USER", "postgres"))
    password = os.getenv("PGPASSWORD", os.getenv("POSTGRES_PASSWORD", ""))
    return f"host={host} port={port} dbname={dbname} user={user} password={password} connect_timeout=10"


def connect_database():
    try:
        import psycopg2
    except ImportError as exc:
        raise RuntimeError("Dépendance absente : installer psycopg2-binary>=2.9,<3") from exc
    connection = psycopg2.connect(database_dsn())
    connection.autocommit = False
    return connection


def initialize_database(connection, specs: list[VariableSpec], args, catalog: Path) -> None:
    with connection.cursor() as cursor:
        cursor.execute(DDL)
        for spec in specs:
            cursor.execute(
                """
                INSERT INTO shelly.p1_variable_registry
                    (variable_id, device_id, firmware_version, rpc_method, component_key,
                     section_name, json_path, variable_name, declared_data_type, category,
                     priority_level, frequency_seconds, classification_rule, catalog_source)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,'instantanée','P1',1,%s,%s)
                ON CONFLICT (variable_id) DO UPDATE SET
                    last_registered_at=now(), enabled=true,
                    classification_rule=EXCLUDED.classification_rule,
                    catalog_source=EXCLUDED.catalog_source
                """,
                (spec.variable_id, args.device_id, args.firmware, spec.rpc_method,
                 spec.component_key, spec.section, spec.json_path, spec.variable_name,
                 spec.data_type, spec.classification_rule, str(catalog.resolve())),
            )
        cursor.execute(
            "SELECT count(*) FROM shelly.p1_variable_registry WHERE device_id=%s AND firmware_version=%s AND enabled",
            (args.device_id, args.firmware),
        )
        count = cursor.fetchone()[0]
        if count != EXPECTED_VARIABLES:
            raise RuntimeError(f"Registre PostgreSQL P1 : {count} variables actives, 40 attendues")
    connection.commit()


def collect_rpc(client: ShellyClient, methods: set[str]) -> tuple[dict[str, RpcCapture], list[dict[str, str]]]:
    captures: dict[str, RpcCapture] = {}
    errors = []
    for method in sorted(methods):
        try:
            captures[method] = client.components_status() if method == "Shelly.GetComponents" else client.call(method)
        except Exception as exc:
            errors.append({"method": method, "error": str(exc)})
    return captures, errors


def persist_cycle(connection, args, specs: list[VariableSpec], scheduled_at: datetime,
                  started_at: datetime, captures: dict[str, RpcCapture], errors: list[dict[str, str]]) -> tuple[int, int]:
    cycle_id = uuid.uuid4()
    completed = utc_now()
    device_ts = device_timestamp(captures)
    received_at = max((c.received_at for c in captures.values()), default=completed)
    duration_ms = round((completed - started_at).total_seconds() * 1000)
    raw_ids: dict[str, int] = {}
    present = 0
    missing = 0

    with connection.cursor() as cursor:
        cursor.execute(
            """INSERT INTO shelly.p1_collection_cycle
               (cycle_id,device_id,scheduled_at,started_at,device_timestamp,expected_variables,
                cycle_status,errors_json,collector_version,collector_host)
               VALUES (%s,%s,%s,%s,%s,%s,'writing',%s::jsonb,%s,%s)""",
            (str(cycle_id), args.device_id, scheduled_at, started_at, device_ts,
             EXPECTED_VARIABLES, canonical_json(errors), VERSION, socket.gethostname()),
        )
        for method, capture in captures.items():
            payload_text = canonical_json(capture.envelope)
            cursor.execute(
                """INSERT INTO shelly.p1_raw_rpc
                   (cycle_id,device_id,rpc_method,requested_at,received_at,duration_ms,
                    payload,payload_sha256,collector_version)
                   VALUES (%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s) RETURNING raw_event_id""",
                (str(cycle_id), args.device_id, method, capture.requested_at, capture.received_at,
                 capture.duration_ms, payload_text, hashlib.sha256(payload_text.encode()).hexdigest(), VERSION),
            )
            raw_ids[method] = cursor.fetchone()[0]

        for spec in specs:
            capture = captures.get(spec.rpc_method)
            value = MISSING
            stored_present = False
            flags: list[str] = []
            if capture:
                if spec.rpc_method == "Shelly.GetComponents":
                    root = component_result(capture, spec.component_key, spec.section)
                else:
                    root = capture.envelope["result"]
                if root is not MISSING:
                    value = extract_path(root, spec.json_path)
            if value is MISSING:
                numeric = text = boolean = json_value = value_type = None
                quality = "missing"
                flags.append("VARIABLE_ABSENTE_REPONSE")
                missing += 1
            else:
                try:
                    numeric, text, boolean, json_value, value_type = typed_value(value)
                    quality = "valid"
                    stored_present = True
                    present += 1
                except ValueError:
                    numeric = text = boolean = json_value = value_type = None
                    quality = "invalid"
                    flags.append("VALEUR_NUMERIQUE_NON_FINIE")
                    missing += 1
            offset_ms = round((device_ts - received_at).total_seconds() * 1000) if device_ts else None
            if offset_ms is not None and abs(offset_ms) > args.max_clock_offset_ms:
                flags.append("DERIVE_HORLOGE")
                if quality == "valid":
                    quality = "warning"
            cursor.execute(
                """INSERT INTO shelly.p1_instantaneous_observation
                   (cycle_id,variable_id,device_id,component_key,rpc_method,json_path,
                    observed_at,received_at,device_timestamp,clock_offset_ms,is_present,
                    numeric_value,text_value,boolean_value,json_value,value_type,
                    quality_status,quality_flags,raw_event_id)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s,%s)""",
                (str(cycle_id), spec.variable_id, args.device_id, spec.component_key,
                 spec.rpc_method, spec.json_path, scheduled_at, received_at, device_ts,
                 offset_ms, stored_present, numeric, text, boolean, json_value,
                 value_type, quality, flags, raw_ids.get(spec.rpc_method)),
            )
        status = "success" if missing == 0 and not errors else "partial" if captures else "failed"
        cursor.execute(
            """UPDATE shelly.p1_collection_cycle SET completed_at=%s,present_variables=%s,
               missing_variables=%s,raw_payload_count=%s,duration_ms=%s,cycle_status=%s
               WHERE cycle_id=%s""",
            (utc_now(), present, missing, len(captures), duration_ms, status, str(cycle_id)),
        )
    connection.commit()
    return present, missing


def signal_handler(_signum, _frame) -> None:
    global STOP_REQUESTED
    STOP_REQUESTED = True


def self_test() -> int:
    assert extract_path({"em:0": {"a_voltage": 230.1}}, "$.em:0.a_voltage") == 230.1
    assert extract_path({}, "$.absent") is MISSING
    assert typed_value(True)[2] is True
    assert typed_value(12.5)[0] == 12.5
    row = {"source_rpc": "Shelly.GetStatus", "composant": "", "section": "status", "chemin_json": "$.x"}
    assert len(stable_variable_id("d", "1", row)) == 32
    print("AUTO-TEST : SUCCÈS")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Collecte Docker/PostgreSQL des 40 variables P1 chaque seconde")
    parser.add_argument("--ip", default=os.getenv("SHELLY_IP", "10.120.157.134"))
    parser.add_argument("--device-id", default=os.getenv("SHELLY_DEVICE_ID", "shellypro3em63-a4f00fccaf68"))
    parser.add_argument("--firmware", default=os.getenv("SHELLY_FIRMWARE", "1.4.0"))
    parser.add_argument("--catalog", type=Path, default=None)
    parser.add_argument("--catalog-root", type=Path, default=Path(os.getenv("SHELLY_CATALOG_ROOT", "shelly_inventory")))
    parser.add_argument("--interval", type=float, default=1.0)
    parser.add_argument("--timeout", type=float, default=0.8)
    parser.add_argument("--max-clock-offset-ms", type=int, default=2000)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--log-level", default=os.getenv("LOG_LEVEL", "INFO"))
    args = parser.parse_args()
    if args.interval < 1.0:
        parser.error("--interval doit être supérieur ou égal à 1 seconde")
    return args


def main() -> int:
    args = parse_args()
    logging.basicConfig(level=getattr(logging, args.log_level.upper(), logging.INFO),
                        format="%(asctime)s [%(levelname)s] %(message)s")
    if args.self_test:
        return self_test()
    self_test()
    catalog = args.catalog.resolve() if args.catalog else find_latest_catalog(args.catalog_root)
    specs = load_specs(catalog, args.device_id, args.firmware)
    methods = {spec.rpc_method for spec in specs}
    LOG.info("Catalogue=%s — variables P1=%d — intervalle=%.1fs", catalog, len(specs), args.interval)

    connection = connect_database()
    initialize_database(connection, specs, args, catalog)
    client = ShellyClient(args.ip, args.timeout)
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)
    next_tick = time.monotonic()

    try:
        while not STOP_REQUESTED:
            scheduled_at = utc_now().replace(microsecond=0)
            started_at = utc_now()
            captures, errors = collect_rpc(client, methods)
            try:
                present, missing = persist_cycle(connection, args, specs, scheduled_at,
                                                 started_at, captures, errors)
                if missing or errors:
                    LOG.warning("Cycle partiel : présentes=%d manquantes=%d erreurs=%s", present, missing, errors)
                else:
                    LOG.info("Cycle conforme : 40/40 variables stockées")
            except Exception:
                connection.rollback()
                LOG.exception("Échec transaction PostgreSQL")
                if connection.closed:
                    connection = connect_database()
                    initialize_database(connection, specs, args, catalog)
            if args.once:
                break
            next_tick += args.interval
            delay = next_tick - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            else:
                LOG.warning("Cycle plus long que %.1fs; retard=%.3fs", args.interval, -delay)
                next_tick = time.monotonic()
    finally:
        connection.close()
        LOG.info("Collecteur P1 arrêté proprement")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
