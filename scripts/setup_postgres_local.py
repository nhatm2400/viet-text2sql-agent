"""Create an isolated Windows demo cluster from an EDB binary ZIP; never reseed an existing DB."""

from __future__ import annotations

import argparse
import hashlib
import json
import secrets
import subprocess
import zipfile
from pathlib import Path

import psycopg
from psycopg import sql
from sqlalchemy import URL

from db.seed import seed

ROOT = Path(__file__).resolve().parents[1]
LOCAL = ROOT / "data" / "postgres_local"
PORT = 55432
SOURCE = "https://sbp.enterprisedb.com/getfile.jsp?fileid=1260616"


def command(*args: str) -> None:
    subprocess.run(args, check=True, creationflags=subprocess.CREATE_NO_WINDOW)


def setup(archive: Path) -> dict:
    LOCAL.mkdir(parents=True, exist_ok=True)
    runtime = LOCAL / "runtime"
    if not (runtime / "pgsql" / "bin" / "initdb.exe").exists():
        with zipfile.ZipFile(archive) as bundle:
            for name in bundle.namelist():
                target = (runtime / name).resolve()
                if not target.is_relative_to(runtime.resolve()):
                    raise ValueError("Unsafe ZIP member")
            bundle.extractall(runtime)
    binaries = runtime / "pgsql" / "bin"
    credentials = LOCAL / "credentials.json"
    if credentials.exists():
        passwords = json.loads(credentials.read_text(encoding="utf-8"))
    else:
        passwords = {"admin": secrets.token_urlsafe(32), "ro": secrets.token_urlsafe(32)}
        credentials.write_text(json.dumps(passwords), encoding="utf-8")
    cluster = LOCAL / "cluster"
    if not (cluster / "PG_VERSION").exists():
        pwfile = LOCAL / "init-password.txt"
        pwfile.write_text(passwords["admin"] + "\n", encoding="utf-8")
        try:
            command(
                str(binaries / "initdb.exe"),
                "-D",
                str(cluster),
                "--username=t2sql_admin",
                "--auth=scram-sha-256",
                "--encoding=UTF8",
                "--locale=C",
                f"--pwfile={pwfile}",
            )
        finally:
            pwfile.unlink(missing_ok=True)
        with (cluster / "postgresql.conf").open("a", encoding="utf-8") as stream:
            stream.write(f"\nlisten_addresses = '127.0.0.1'\nport = {PORT}\n")
    status = subprocess.run(
        [str(binaries / "pg_ctl.exe"), "-D", str(cluster), "status"],
        capture_output=True,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    if status.returncode:
        command(
            str(binaries / "pg_ctl.exe"),
            "-D",
            str(cluster),
            "-l",
            str(LOCAL / "server.log"),
            "-w",
            "start",
        )
    connection = dict(host="127.0.0.1", port=PORT, user="t2sql_admin", password=passwords["admin"])
    with psycopg.connect(dbname="postgres", autocommit=True, **connection) as conn:
        exists = conn.execute("SELECT 1 FROM pg_database WHERE datname = 't2sql'").fetchone()
        if not exists:
            conn.execute("CREATE DATABASE t2sql")
    admin_url = URL.create(
        "postgresql+psycopg",
        username="t2sql_admin",
        password=passwords["admin"],
        host="127.0.0.1",
        port=PORT,
        database="t2sql",
    ).render_as_string(hide_password=False)
    ro_url = URL.create(
        "postgresql+psycopg",
        username="t2sql_ro",
        password=passwords["ro"],
        host="127.0.0.1",
        port=PORT,
        database="t2sql",
    ).render_as_string(hide_password=False)
    with psycopg.connect(dbname="t2sql", **connection) as conn:
        tables = conn.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
        ).fetchall()
    if not tables:
        seed(admin_url, drop=False, version="v2")
    with psycopg.connect(dbname="t2sql", **connection) as conn:
        conn.execute((ROOT / "db" / "traces.sql").read_text(encoding="utf-8"))
        role_script = (ROOT / "db" / "roles.sql").read_text(encoding="utf-8")
        role_script = "\n".join(
            line for line in role_script.splitlines() if not line.startswith("\\")
        )
        role_script = role_script.replace(
            ":ro_password", sql.Literal(passwords["ro"]).as_string(conn)
        )
        conn.execute(role_script)
        counts = {
            name: conn.execute(
                sql.SQL("SELECT COUNT(*) FROM {}").format(sql.Identifier(name))
            ).fetchone()[0]
            for (name,) in tables
            if name != "agent_traces"
        }
        version = conn.execute("SHOW server_version").fetchone()[0]
    # Count the newly seeded tables as well, without publishing URLs or passwords.
    if not counts:
        with psycopg.connect(dbname="t2sql", **connection) as conn:
            names = conn.execute(
                "SELECT tablename FROM pg_tables WHERE schemaname = 'public' AND tablename <> 'agent_traces'"
            ).fetchall()
            counts = {
                name: conn.execute(
                    sql.SQL("SELECT COUNT(*) FROM {}").format(sql.Identifier(name))
                ).fetchone()[0]
                for (name,) in names
            }
    profile = LOCAL / "demo.env"
    profile.write_text(
        "OFFLINE_MODE=0\nMODEL_PROVIDER=ollama_local\nMODEL_FAST=qwen3:4b\nMODEL_STRONG=qwen3:4b\nMODEL_MAX_TOKENS=4096\nOLLAMA_BASE_URL=http://127.0.0.1:11434\nOLLAMA_NUM_CTX=8192\nOLLAMA_SEED=42\nMAX_ITERATIONS=6\n"
        f"DATABASE_URL={admin_url}\nDATABASE_URL_RO={ro_url}\n",
        encoding="utf-8",
    )
    evidence = {
        "server_version": version,
        "host": "127.0.0.1",
        "port": PORT,
        "seed_version": "v2",
        "table_counts": counts,
        "archive_source": SOURCE,
        "archive_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
        "checksum_is_locally_recorded_not_vendor_attestation": True,
    }
    (LOCAL / "setup.json").write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    return evidence


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, default=LOCAL / "postgresql-17.11-windows-x64.zip")
    print(json.dumps(setup(parser.parse_args().archive), indent=2))
