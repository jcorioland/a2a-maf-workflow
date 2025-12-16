#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request


def _check_healthz(url: str, timeout_s: float) -> tuple[bool, str]:
    """Returns (ready, message). Ready means HTTP 200 and JSON has initialized==true."""

    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            if resp.status != 200:
                return False, f"HTTP {resp.status}"
            body = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        return False, f"HTTP {exc.code}"
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"

    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return False, "invalid JSON"

    initialized = bool(payload.get("initialized", False))
    status = payload.get("status")
    service = payload.get("service")

    if initialized:
        return True, f"ready (service={service}, status={status})"

    return False, f"not initialized (service={service}, status={status})"


def main() -> int:
    parser = argparse.ArgumentParser(description="Wait for agent /healthz endpoints to be initialized")
    parser.add_argument("--writer-url", default="http://127.0.0.1:8000/healthz")
    parser.add_argument("--reviewer-url", default="http://127.0.0.1:8001/healthz")
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--interval", type=float, default=0.5)
    parser.add_argument("--request-timeout", type=float, default=2.0)
    args = parser.parse_args()

    start = time.time()
    last_print = 0.0

    while True:
        writer_ready, writer_msg = _check_healthz(args.writer_url, timeout_s=args.request_timeout)
        reviewer_ready, reviewer_msg = _check_healthz(args.reviewer_url, timeout_s=args.request_timeout)

        now = time.time()
        if now - last_print >= 2.0:
            elapsed = now - start
            print(
                f"[wait_for_agents] {elapsed:5.1f}s writer={writer_ready} ({writer_msg}) reviewer={reviewer_ready} ({reviewer_msg})",
                flush=True,
            )
            last_print = now

        if writer_ready and reviewer_ready:
            print("[wait_for_agents] both agents ready", flush=True)
            return 0

        if now - start >= args.timeout:
            print("[wait_for_agents] timed out waiting for agents", file=sys.stderr, flush=True)
            return 1

        time.sleep(args.interval)


if __name__ == "__main__":
    raise SystemExit(main())
