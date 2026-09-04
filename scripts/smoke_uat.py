#!/usr/bin/env python3
"""Non-destructive deployed smoke/UAT: liveness, readiness, login, /me."""
from __future__ import annotations
import argparse
import json
import sys
from urllib import request, error


def call(url: str, method="GET", payload=None, token=None):
    data = json.dumps(payload).encode() if payload is not None else None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = request.Request(url, data=data, headers=headers, method=method)
    with request.urlopen(req, timeout=10) as resp:
        body = resp.read().decode()
        return resp.status, json.loads(body) if body else {}


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--base-url", default="http://localhost:8080")
    p.add_argument("--username")
    p.add_argument("--password")
    args = p.parse_args()
    base = args.base_url.rstrip("/")
    try:
        status, body = call(base + "/health/live")
        assert status == 200 and body.get("status") == "ok"
        print("PASS liveness")
        status, body = call(base + "/health/ready")
        assert status == 200 and body.get("database") == "ok"
        print("PASS database readiness")
        if args.username and args.password:
            _, login = call(base + "/api/v1/auth/login", "POST", {"username": args.username, "password": args.password})
            token = login["access_token"]
            print("PASS authentication")
            _, me = call(base + "/api/v1/auth/me", token=token)
            assert me.get("username") == args.username
            assert me.get("roles")
            print(f"PASS identity/roles ({', '.join(me['roles'])})")
        else:
            print("SKIP authenticated smoke (provide --username and --password)")
    except (AssertionError, KeyError, error.URLError, error.HTTPError) as exc:
        print(f"FAIL smoke/UAT: {exc}", file=sys.stderr)
        return 1
    print("Smoke/UAT PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
