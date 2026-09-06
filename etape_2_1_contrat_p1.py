#!/usr/bin/env python3
"""Étape 2.1 — construire, sceller et contrôler le contrat P1 canonique.

Entrée : 03_04_catalogue_variables_classees.csv produit par l'inventaire Shelly.
Sorties : dictionnaire CSV v2, manifeste JSON SHA-256 et rapport JSON.

Le programme ne modifie jamais le catalogue source et refuse d'écraser un contrat
différent déjà produit sous la même version.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import sys
import tempfile
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

TOOL_VERSION = "1.0.0"
DEFAULT_CONTRACT_VERSION = "2.0.0"
CANONICAL_RPC = "Shelly.GetStatus"
RECLASSIFIED_PATHS = {
    "$.em:0.total_current",
    "$.em:0.total_act_power",
    "$.em:0.total_aprt_power",
}
OUTPUT_FIELDS = (
    "variable_id", "nom_variable", "chemin_json", "source_rpc", "composant",
    "section", "unite", "type_donnee", "categorie", "priorite",
    "frequence_secondes", "firmware", "appareil", "statut",
    "regle_classification", "catalogue_version",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def normalized(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    return "".join(ch for ch in text if not unicodedata.combining(ch)).strip().lower()


def first(row: dict[str, str], *names: str) -> str:
    index = {normalized(key): value for key, value in row.items()}
    for name in names:
        value = index.get(normalized(name))
        if value is not None:
            return str(value).strip()
    return ""


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def stable_id(device: str, firmware: str, path: str) -> str:
    identity = f"{device}|{firmware}|{CANONICAL_RPC}|{path}"
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()[:32]


def atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() == data:
            return
        raise FileExistsError(
            f"Refus d'écraser {path}: une version différente existe déjà. "
            "Incrémentez --contract-version."
        )
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as tmp:
        tmp.write(data)
        temporary = Path(tmp.name)
    temporary.replace(path)


def csv_bytes(rows: list[dict[str, str]]) -> bytes:
    import io
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=OUTPUT_FIELDS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8-sig")


def read_source(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if not reader.fieldnames:
            raise ValueError("Le catalogue CSV ne possède pas d'en-tête")
        return list(reader)


def build_contract(source_rows: list[dict[str, str]], args: argparse.Namespace) -> list[dict[str, str]]:
    selected: dict[str, dict[str, str]] = {}
    for row in source_rows:
        rpc = first(row, "source_rpc", "rpc_method", "methode_rpc")
        path = first(row, "chemin_json", "json_path")
        category = normalized(first(row, "categorie", "category"))
        if rpc != CANONICAL_RPC or not path:
            continue
        is_instantaneous = category in {"instantanee", "instantane"} or path in RECLASSIFIED_PATHS
        if not is_instantaneous:
            continue
        if path in selected:
            raise ValueError(f"Doublon canonique dans le catalogue source : {path}")
        selected[path] = {
            "variable_id": stable_id(args.device_id, args.firmware, path),
            "nom_variable": first(row, "nom_variable", "variable_name") or path.rsplit(".", 1)[-1],
            "chemin_json": path,
            "source_rpc": CANONICAL_RPC,
            "composant": first(row, "composant", "component_key"),
            "section": first(row, "section", "section_name") or "status",
            "unite": first(row, "unite", "unit"),
            "type_donnee": first(row, "type_donnee", "data_type", "type") or "number",
            "categorie": "instantanee",
            "priorite": "P1",
            "frequence_secondes": "1",
            "firmware": args.firmware,
            "appareil": args.device_id,
            "statut": "ACTIF",
            "regle_classification": (
                "RECLASSE_TOTAL_MOMENTANE_V2" if path in RECLASSIFIED_PATHS
                else first(row, "regle_appliquee", "classification_rule") or "CATALOGUE_INSTANTANE"
            ),
            "catalogue_version": args.contract_version,
        }
    missing = sorted(RECLASSIFIED_PATHS - selected.keys())
    if missing:
        raise ValueError("Chemins instantanés obligatoires absents : " + ", ".join(missing))
    rows = [selected[path] for path in sorted(selected)]
    if args.expected_count is not None and len(rows) != args.expected_count:
        raise ValueError(
            f"Contrat refusé : {len(rows)} variables trouvées, {args.expected_count} attendues. "
            "Ne signez pas avant réconciliation."
        )
    return rows


def manifest_payload(args: argparse.Namespace, source: Path, dictionary: Path,
                     rows: list[dict[str, str]], dictionary_sha: str) -> dict[str, Any]:
    approved = bool(args.approved_by and args.approval_reference)
    return {
        "schema": "shelly-p1-contract-manifest/v1",
        "status": "APPROVED" if approved else "DRAFT",
        "contract_version": args.contract_version,
        "generated_at_utc": utc_now(),
        "device_id": args.device_id,
        "firmware": args.firmware,
        "canonical_rpc": CANONICAL_RPC,
        "frequency_seconds": 1,
        "variable_count": len(rows),
        "source_catalogue": source.name,
        "source_catalogue_sha256": sha256_file(source),
        "dictionary_file": dictionary.name,
        "dictionary_sha256": dictionary_sha,
        "generator": Path(__file__).name,
        "generator_version": TOOL_VERSION,
        "approved_by": args.approved_by or None,
        "approval_reference": args.approval_reference or None,
        "approval_date": args.approval_date or None,
        "notice": "Le SHA-256 prouve l'intégrité; l'approbation humaine autorise l'usage.",
    }


DDL = """
CREATE SCHEMA IF NOT EXISTS governance;
CREATE TABLE IF NOT EXISTS governance.p1_catalog_contract (
  contract_version text PRIMARY KEY,
  status text NOT NULL CHECK (status IN ('DRAFT','APPROVED','RETIRED')),
  device_id text NOT NULL,
  firmware text NOT NULL,
  canonical_rpc text NOT NULL,
  frequency_seconds integer NOT NULL,
  variable_count integer NOT NULL,
  dictionary_sha256 char(64) NOT NULL,
  source_catalogue_sha256 char(64) NOT NULL,
  manifest jsonb NOT NULL,
  registered_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS governance.p1_catalog_variable (
  contract_version text NOT NULL REFERENCES governance.p1_catalog_contract(contract_version),
  variable_id text NOT NULL,
  json_path text NOT NULL,
  variable_name text NOT NULL,
  rpc_method text NOT NULL,
  unit text,
  data_type text NOT NULL,
  priority_level text NOT NULL,
  frequency_seconds integer NOT NULL,
  classification_rule text NOT NULL,
  PRIMARY KEY (contract_version, variable_id),
  UNIQUE (contract_version, rpc_method, json_path)
);
"""


def db_connection():
    dsn = os.getenv("PG_DSN", "").strip()
    if not dsn:
        raise RuntimeError("PG_DSN absent. Aucun secret ne doit être écrit dans le script.")
    try:
        import psycopg2
    except ImportError as exc:
        raise RuntimeError("Installer psycopg2-binary>=2.9,<3") from exc
    connection = psycopg2.connect(dsn)
    connection.autocommit = False
    return connection


def register_contract(rows: list[dict[str, str]], manifest: dict[str, Any]) -> None:
    connection = db_connection()
    try:
        with connection.cursor() as cur:
            cur.execute(DDL)
            cur.execute(
                "SELECT dictionary_sha256 FROM governance.p1_catalog_contract WHERE contract_version=%s",
                (manifest["contract_version"],),
            )
            existing = cur.fetchone()
            if existing and existing[0].strip() != manifest["dictionary_sha256"]:
                raise RuntimeError("Version déjà enregistrée avec une autre empreinte")
            cur.execute(
                """INSERT INTO governance.p1_catalog_contract
                   (contract_version,status,device_id,firmware,canonical_rpc,frequency_seconds,
                    variable_count,dictionary_sha256,source_catalogue_sha256,manifest)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)
                   ON CONFLICT (contract_version) DO NOTHING""",
                (manifest["contract_version"], manifest["status"], manifest["device_id"],
                 manifest["firmware"], manifest["canonical_rpc"], manifest["frequency_seconds"],
                 manifest["variable_count"], manifest["dictionary_sha256"],
                 manifest["source_catalogue_sha256"], json.dumps(manifest, ensure_ascii=False)),
            )
            for row in rows:
                cur.execute(
                    """INSERT INTO governance.p1_catalog_variable
                       (contract_version,variable_id,json_path,variable_name,rpc_method,unit,data_type,
                        priority_level,frequency_seconds,classification_rule)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                       ON CONFLICT (contract_version,variable_id) DO NOTHING""",
                    (manifest["contract_version"], row["variable_id"], row["chemin_json"],
                     row["nom_variable"], row["source_rpc"], row["unite"], row["type_donnee"],
                     row["priorite"], int(row["frequence_secondes"]), row["regle_classification"]),
                )
            cur.execute(
                "SELECT count(*) FROM governance.p1_catalog_variable WHERE contract_version=%s",
                (manifest["contract_version"],),
            )
            if cur.fetchone()[0] != manifest["variable_count"]:
                raise RuntimeError("Nombre de variables différent après enregistrement PostgreSQL")
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def audit_database(manifest: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {"status": "FAIL", "checks": {}}
    connection = db_connection()
    try:
        with connection.cursor() as cur:
            cur.execute("SELECT to_regclass('shelly.p1_variable_registry') IS NOT NULL")
            registry_exists = cur.fetchone()[0]
            cur.execute("SELECT to_regclass('shelly.p1_collection_cycle') IS NOT NULL")
            cycle_exists = cur.fetchone()[0]
            result["checks"]["registry_exists"] = registry_exists
            result["checks"]["cycle_table_exists"] = cycle_exists
            if registry_exists:
                cur.execute(
                    """SELECT count(*) FROM shelly.p1_variable_registry
                       WHERE device_id=%s AND firmware_version=%s AND enabled""",
                    (manifest["device_id"], manifest["firmware"]),
                )
                result["active_registry_count"] = cur.fetchone()[0]
            if cycle_exists:
                cur.execute(
                    """SELECT collector_version,expected_variables,present_variables,
                              missing_variables,raw_payload_count,cycle_status,scheduled_at
                       FROM shelly.p1_collection_cycle WHERE device_id=%s
                       ORDER BY inserted_at DESC LIMIT 1""",
                    (manifest["device_id"],),
                )
                row = cur.fetchone()
                if row:
                    result["latest_cycle"] = {
                        "collector_version": row[0], "expected_variables": row[1],
                        "present_variables": row[2], "missing_variables": row[3],
                        "raw_payload_count": row[4], "cycle_status": row[5],
                        "scheduled_at": row[6].isoformat(),
                    }
        expected = manifest["variable_count"]
        cycle = result.get("latest_cycle", {})
        checks = result["checks"]
        checks["registry_matches_contract"] = result.get("active_registry_count") == expected
        checks["cycle_expected_matches_contract"] = cycle.get("expected_variables") == expected
        checks["canonical_single_payload"] = cycle.get("raw_payload_count") == 1
        checks["cycle_complete"] = (
            cycle.get("present_variables") == expected
            and cycle.get("missing_variables") == 0
            and cycle.get("cycle_status") == "success"
        )
        checks["collector_v2_or_later"] = str(cycle.get("collector_version", "")).startswith("2.")
        result["status"] = "PASS" if all(checks.values()) else "FAIL"
        return result
    finally:
        connection.close()


def self_test() -> int:
    rows = [
        {"source_rpc": CANONICAL_RPC, "categorie": "instantanée", "chemin_json": "$.em:0.a_voltage", "nom_variable": "a_voltage"},
        {"source_rpc": "Shelly.GetComponents", "categorie": "instantanée", "chemin_json": "$.a_voltage", "nom_variable": "a_voltage"},
        *[
            {"source_rpc": CANONICAL_RPC, "categorie": "cumulative", "chemin_json": path, "nom_variable": path.rsplit('.', 1)[-1]}
            for path in sorted(RECLASSIFIED_PATHS)
        ],
    ]
    args = argparse.Namespace(device_id="device", firmware="1.4.0", contract_version="2.0.0", expected_count=4)
    built = build_contract(rows, args)
    assert len(built) == 4
    assert all(row["source_rpc"] == CANONICAL_RPC for row in built)
    assert len({row["variable_id"] for row in built}) == 4
    print("AUTO-TEST : SUCCÈS")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, help="Chemin du catalogue classé source")
    parser.add_argument("--output-dir", type=Path, default=Path("contrats_p1"))
    parser.add_argument("--device-id", default="shellypro3em63-a4f00fccaf68")
    parser.add_argument("--firmware", default="1.4.0")
    parser.add_argument("--contract-version", default=DEFAULT_CONTRACT_VERSION)
    parser.add_argument("--expected-count", type=int, default=23)
    parser.add_argument("--approved-by")
    parser.add_argument("--approval-reference")
    parser.add_argument("--approval-date")
    parser.add_argument("--register-db", action="store_true")
    parser.add_argument("--audit-db", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.self_test:
        return self_test()
    if not args.catalog or not args.catalog.is_file():
        raise SystemExit("ERREUR : fournir un catalogue existant avec --catalog")
    if bool(args.approved_by) != bool(args.approval_reference):
        raise SystemExit("ERREUR : --approved-by et --approval-reference sont indissociables")

    rows = build_contract(read_source(args.catalog), args)
    # Chaque exécution possède son dossier de preuve : un brouillon puis une
    # approbation ne s'écrasent jamais, même sous la même version contractuelle.
    run_stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_status = "approved" if args.approved_by else "draft"
    output = (args.output_dir / f"v{args.contract_version}" / f"{run_stamp}_{run_status}").resolve()
    dictionary = output / f"catalogue_p1_v{args.contract_version}.csv"
    dictionary_data = csv_bytes(rows)
    dictionary_sha = sha256_bytes(dictionary_data)
    manifest = manifest_payload(args, args.catalog, dictionary, rows, dictionary_sha)
    manifest_path = output / f"catalogue_p1_v{args.contract_version}.manifest.json"
    report_path = output / f"catalogue_p1_v{args.contract_version}.rapport.json"

    atomic_write(dictionary, dictionary_data)
    atomic_write(manifest_path, (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))

    report: dict[str, Any] = {
        "generated_at_utc": utc_now(), "contract": manifest,
        "local_checks": {
            "canonical_rpc_only": all(r["source_rpc"] == CANONICAL_RPC for r in rows),
            "unique_json_paths": len({r["chemin_json"] for r in rows}) == len(rows),
            "stable_unique_ids": len({r["variable_id"] for r in rows}) == len(rows),
            "expected_count": len(rows) == args.expected_count,
            "mandatory_totals_present": RECLASSIFIED_PATHS <= {r["chemin_json"] for r in rows},
        },
    }
    if args.register_db:
        register_contract(rows, manifest)
        report["database_registration"] = "SUCCESS"
    if args.audit_db:
        report["database_audit"] = audit_database(manifest)
    report["status"] = "PASS" if all(report["local_checks"].values()) else "FAIL"
    if args.audit_db and report["database_audit"]["status"] != "PASS":
        report["status"] = "FAIL"
    atomic_write(report_path, (json.dumps(report, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))

    print(f"CONTRAT P1 : {manifest['status']}")
    print(f"Variables canoniques : {len(rows)}")
    print(f"Dictionnaire : {dictionary}")
    print(f"SHA-256 : {dictionary_sha}")
    print(f"Rapport : {report_path}")
    print(f"VERDICT : {report['status']}")
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERREUR : {exc}", file=sys.stderr)
        raise SystemExit(1)
