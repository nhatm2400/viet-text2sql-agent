"""Keep-alive / health probe. Runs on the VPS from cron.

    */5 * * * * t2sql /opt/t2sql/.venv/bin/python /opt/t2sql/scripts/keepalive_ping.py

This is a *process* health check, not a container health check: it polls the API's `/health`
endpoint over loopback and, if the service is unreachable, asks systemd to restart it. systemd's
own `Restart=on-failure` covers a crashed process; this covers the other case — a process that is
alive but wedged, which systemd cannot see.

A VPS does not sleep, so unlike free-tier managed platforms there is no cold start to warm up.
The purpose here is purely to make "demo dead when a reviewer clicks" a detected event.

Exit codes: 0 healthy · 1 unhealthy (restart attempted) · 2 probe could not run.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import UTC, datetime

DEFAULT_URL = f"http://127.0.0.1:{os.getenv('API_PORT', '8000')}/health"
SERVICES = ("t2sql-api", "t2sql-ui")


def log(message: str) -> None:
    print(f"{datetime.now(UTC):%Y-%m-%d %H:%M:%S}Z keepalive: {message}", flush=True)


def probe(url: str, timeout: float) -> tuple[bool, str]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:  # noqa: S310 - loopback only
            if response.status != 200:
                return False, f"HTTP {response.status}"
            payload = json.loads(response.read().decode("utf-8"))
            if payload.get("status") != "ok":
                return False, f"unhealthy payload: {payload}"
            return True, (
                f"ok (offline_mode={payload.get('offline_mode')}, "
                f"db={'yes' if payload.get('database_configured') else 'no'})"
            )
    except urllib.error.URLError as err:
        return False, f"unreachable: {err.reason}"
    except (TimeoutError, json.JSONDecodeError, OSError) as err:
        return False, f"probe failed: {err}"


def restart(services: tuple[str, ...], dry_run: bool) -> None:
    for service in services:
        if dry_run:
            log(f"[dry-run] would restart {service}")
            continue
        try:
            subprocess.run(["systemctl", "restart", service], check=True, timeout=60)
            log(f"restarted {service}")
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError) as err:
            log(f"could not restart {service}: {err}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ping the API and restart it if it is wedged")
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--no-restart", action="store_true", help="report only, never restart")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    healthy, detail = probe(args.url, args.timeout)
    log(f"{args.url} -> {detail}")
    if healthy:
        return 0

    if args.no_restart:
        return 1
    restart(SERVICES, args.dry_run)

    healthy_after, detail_after = probe(args.url, args.timeout)
    log(f"after restart: {detail_after}")
    return 0 if healthy_after else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(2)
