#!/usr/bin/env python3
"""Production deployment preflight. Uses only Python stdlib."""
from __future__ import annotations
import argparse
import os
from pathlib import Path
import shutil
import sys
from urllib.parse import urlparse

PLACEHOLDERS = ("REPLACE_", "change-me", "dev-only", "example.com")


def load_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        values[k.strip()] = v.strip().strip('"').strip("'")
    return values


def fail(errors: list[str], message: str) -> None:
    errors.append(message)
    print(f"FAIL: {message}")


def ok(message: str) -> None:
    print(f" OK : {message}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", default=".env.production")
    parser.add_argument("--require-bootstrap", action="store_true", help="Require first-run clinic user passwords")
    args = parser.parse_args()
    env_path = Path(args.env_file)
    errors: list[str] = []

    if not env_path.exists():
        fail(errors, f"Missing {env_path}")
        return 1
    env = load_env(env_path)

    required = ["POSTGRES_DB", "POSTGRES_USER", "POSTGRES_PASSWORD", "DATABASE_URL", "JWT_SECRET", "API_CORS_ORIGINS", "TRUSTED_HOSTS"]
    for key in required:
        if not env.get(key):
            fail(errors, f"{key} is required")
        else:
            ok(f"{key} is present")

    secret = env.get("JWT_SECRET", "")
    if len(secret) < 32 or any(x.lower() in secret.lower() for x in ("replace", "dev-only", "change-me")):
        fail(errors, "JWT_SECRET must be random, non-default, and at least 32 characters")
    else:
        ok("JWT_SECRET strength check")

    pg_password = env.get("POSTGRES_PASSWORD", "")
    if len(pg_password) < 16 or any(x.lower() in pg_password.lower() for x in ("replace", "change-me")):
        fail(errors, "POSTGRES_PASSWORD must be non-default and at least 16 characters")
    else:
        ok("POSTGRES_PASSWORD strength check")

    cors = [x.strip() for x in env.get("API_CORS_ORIGINS", "").split(",") if x.strip()]
    if "*" in cors:
        fail(errors, "Wildcard CORS is prohibited")
    elif not cors:
        fail(errors, "At least one CORS origin is required")
    else:
        ok("CORS is explicit")

    hosts = [x.strip() for x in env.get("TRUSTED_HOSTS", "").split(",") if x.strip()]
    if not hosts or "*" in hosts:
        fail(errors, "TRUSTED_HOSTS must be explicit")
    else:
        ok("Trusted hosts are explicit")

    db_url = env.get("DATABASE_URL", "")
    if "change-me" in db_url or "REPLACE_" in db_url:
        fail(errors, "DATABASE_URL still contains a placeholder")
    elif db_url:
        parsed = urlparse(db_url.replace("postgresql+psycopg", "postgresql", 1))
        if parsed.hostname != "db":
            print(f"WARN: DATABASE_URL host is {parsed.hostname!r}; production Compose normally uses 'db'")
        else:
            ok("DATABASE_URL points to internal db service")

    if env.get("API_DOCS_ENABLED", "false").lower() not in {"false", "0", "no"}:
        print("WARN: API docs are enabled in production")
    else:
        ok("Production API docs disabled")

    if args.require_bootstrap:
        for key in [
            "BOOTSTRAP_SUPER_ADMIN_PASSWORD",
            "BOOTSTRAP_ADMIN_PASSWORD",
            "BOOTSTRAP_RECEPTION_PASSWORD",
            "BOOTSTRAP_SUPER_RECEPTION_PASSWORD",
            "BOOTSTRAP_DOCTOR_PASSWORD",
        ]:
            value = env.get(key, "")
            if len(value) < 12 or "replace" in value.lower() or "change-me" in value.lower():
                fail(errors, f"{key} must be a unique non-placeholder password of at least 12 characters for first deployment")
            else:
                ok(f"{key} first-run check")

    compose = Path("docker-compose.prod.yml")
    if compose.exists():
        ok("docker-compose.prod.yml present")
    else:
        fail(errors, "docker-compose.prod.yml missing")

    if shutil.which("docker"):
        ok("Docker executable available")
    else:
        print("WARN: Docker executable not found on this machine; Compose cannot be launched here")

    try:
        mode = env_path.stat().st_mode & 0o777
        if mode & 0o077:
            print(f"WARN: {env_path} permissions are {oct(mode)}; recommend chmod 600")
        else:
            ok("Environment file permissions are restricted")
    except OSError:
        pass

    if errors:
        print(f"\nPreflight FAILED with {len(errors)} error(s).")
        return 1
    print("\nPreflight PASSED.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
