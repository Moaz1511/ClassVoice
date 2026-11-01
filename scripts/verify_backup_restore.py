"""Run an isolated PostgreSQL and S3-compatible backup/restore drill.

Only fixed ``classvoice_p407_*`` databases, buckets, and container-temporary
files are created or removed. The live ``classvoice`` database is read through
``pg_dump`` but is never modified.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE_DB = "classvoice_p407_source"
RESTORE_DB = "classvoice_p407_restore"
BASE_DUMP = "/tmp/classvoice-p407-base.dump"
TEST_DUMP = "/tmp/classvoice-p407-test.dump"
SOURCE_BUCKET = "classvoice-p407-source"
BACKUP_BUCKET = "classvoice-p407-backup"
OBJECT_KEY = "restore-probe/hostname.txt"
RESTORED_OBJECT = "/tmp/classvoice-p407-restored-object"
MARKER = "classvoice-p407-backup-restore-probe-v1"


def run(*args: str, check: bool = True) -> str:
    process = subprocess.run(
        args,
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if check and process.returncode != 0:
        command = " ".join(args[:4])
        raise RuntimeError(f"{command} failed with exit code {process.returncode}")
    return process.stdout.strip()


def postgres(*args: str, check: bool = True) -> str:
    return run("docker", "compose", "exec", "-T", "postgres", *args, check=check)


def storage(*args: str, check: bool = True) -> str:
    return run("docker", "compose", "exec", "-T", "storage", *args, check=check)


def query(database: str, sql: str) -> str:
    return postgres("psql", "-U", "classvoice", "-d", database, "-Atc", sql)


def drop_database(name: str) -> None:
    if name not in {SOURCE_DB, RESTORE_DB}:
        raise ValueError("refusing to drop an unexpected database")
    postgres(
        "psql",
        "-U",
        "classvoice",
        "-d",
        "postgres",
        "-v",
        "ON_ERROR_STOP=1",
        "-c",
        f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);',
        check=False,
    )


def remove_bucket(name: str) -> None:
    if name not in {SOURCE_BUCKET, BACKUP_BUCKET}:
        raise ValueError("refusing to remove an unexpected bucket")
    storage("awslocal", "s3", "rb", f"s3://{name}", "--force", check=False)


def schema_fingerprint(database: str) -> str:
    sql = """
SELECT md5(string_agg(
  table_schema || '.' || table_name || '.' || column_name || ':' ||
  data_type || ':' || is_nullable,
  ',' ORDER BY table_schema, table_name, ordinal_position
))
FROM information_schema.columns
WHERE table_schema = 'public';
""".strip()
    return query(database, sql)


def cleanup() -> None:
    drop_database(SOURCE_DB)
    drop_database(RESTORE_DB)
    postgres("rm", "-f", BASE_DUMP, TEST_DUMP, check=False)
    remove_bucket(SOURCE_BUCKET)
    remove_bucket(BACKUP_BUCKET)
    storage("rm", "-f", RESTORED_OBJECT, check=False)


def main() -> int:
    started = time.perf_counter()
    report: dict[str, object] = {"status": "fail"}
    try:
        cleanup()
        postgres(
            "pg_dump",
            "-U",
            "classvoice",
            "-d",
            "classvoice",
            "-Fc",
            "-f",
            BASE_DUMP,
        )
        postgres("createdb", "-U", "classvoice", SOURCE_DB)
        postgres(
            "pg_restore",
            "-U",
            "classvoice",
            "-d",
            SOURCE_DB,
            "--no-owner",
            "--no-privileges",
            BASE_DUMP,
        )
        query(
            SOURCE_DB,
            "CREATE TABLE public.p407_restore_probe "
            "(id integer PRIMARY KEY, marker text NOT NULL); "
            f"INSERT INTO public.p407_restore_probe VALUES (1, '{MARKER}');",
        )
        postgres(
            "pg_dump",
            "-U",
            "classvoice",
            "-d",
            SOURCE_DB,
            "-Fc",
            "-f",
            TEST_DUMP,
        )
        database_backup_sha256 = postgres("sha256sum", TEST_DUMP).split()[0]
        postgres("createdb", "-U", "classvoice", RESTORE_DB)
        postgres(
            "pg_restore",
            "-U",
            "classvoice",
            "-d",
            RESTORE_DB,
            "--no-owner",
            "--no-privileges",
            TEST_DUMP,
        )

        source_fingerprint = schema_fingerprint(SOURCE_DB)
        restore_fingerprint = schema_fingerprint(RESTORE_DB)
        source_tables = int(
            query(
                SOURCE_DB,
                "SELECT count(*) FROM information_schema.tables "
                "WHERE table_schema='public' AND table_type='BASE TABLE';",
            )
        )
        restore_tables = int(
            query(
                RESTORE_DB,
                "SELECT count(*) FROM information_schema.tables "
                "WHERE table_schema='public' AND table_type='BASE TABLE';",
            )
        )
        restored_marker = query(
            RESTORE_DB,
            "SELECT marker FROM public.p407_restore_probe WHERE id=1;",
        )
        migration_version = query(RESTORE_DB, "SELECT version_num FROM alembic_version;")

        storage("awslocal", "s3api", "create-bucket", "--bucket", SOURCE_BUCKET)
        storage("awslocal", "s3api", "create-bucket", "--bucket", BACKUP_BUCKET)
        object_sha256 = storage("sha256sum", "/etc/hostname").split()[0]
        storage(
            "awslocal",
            "s3api",
            "put-object",
            "--bucket",
            SOURCE_BUCKET,
            "--key",
            OBJECT_KEY,
            "--body",
            "/etc/hostname",
        )
        storage("awslocal", "s3", "sync", f"s3://{SOURCE_BUCKET}", f"s3://{BACKUP_BUCKET}")
        storage(
            "awslocal",
            "s3api",
            "delete-object",
            "--bucket",
            SOURCE_BUCKET,
            "--key",
            OBJECT_KEY,
        )
        storage("awslocal", "s3", "sync", f"s3://{BACKUP_BUCKET}", f"s3://{SOURCE_BUCKET}")
        storage(
            "awslocal",
            "s3api",
            "get-object",
            "--bucket",
            SOURCE_BUCKET,
            "--key",
            OBJECT_KEY,
            RESTORED_OBJECT,
        )
        restored_object_sha256 = storage("sha256sum", RESTORED_OBJECT).split()[0]

        checks = {
            "schema_fingerprint_matches": source_fingerprint == restore_fingerprint,
            "table_count_matches": source_tables == restore_tables,
            "sentinel_matches": restored_marker == MARKER,
            "object_checksum_matches": object_sha256 == restored_object_sha256,
            "migration_head_present": bool(migration_version),
        }
        if not all(checks.values()):
            raise RuntimeError("one or more restore integrity checks failed")
        report = {
            "status": "pass",
            "database": {
                "backup_sha256": database_backup_sha256,
                "schema_fingerprint": restore_fingerprint,
                "public_table_count": restore_tables,
                "migration_version": migration_version,
                "sentinel_sha256": hashlib.sha256(MARKER.encode()).hexdigest(),
            },
            "object_storage": {
                "object_sha256": restored_object_sha256,
                "restored_objects": 1,
            },
            "checks": checks,
            "elapsed_seconds": round(time.perf_counter() - started, 3),
        }
    except Exception as error:  # noqa: BLE001 - boundary emits only error type
        report = {
            "status": "fail",
            "error_type": type(error).__name__,
            "elapsed_seconds": round(time.perf_counter() - started, 3),
        }
    finally:
        cleanup()

    print(json.dumps(report, sort_keys=True))
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
