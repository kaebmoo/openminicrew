"""Diagnose connectivity to the lotto API.

Usage:
    python scripts/check_lotto_api.py
    python scripts/check_lotto_api.py 01112567   # specific draw

Checks (in order):
    1. DNS resolution for lotto.api.rayriffy.com
    2. Direct HTTPS GET to /latest (or /lotto/<date>)
    3. Fallback via codetabs proxy
    4. /list/1 endpoint
"""
import socket
import sys
import time

import requests

API_BASE = "https://lotto.api.rayriffy.com"
HOST = "lotto.api.rayriffy.com"
HEADERS = {"User-Agent": "Mozilla/5.0"}


def step(title):
    print(f"\n=== {title} ===")


def check_dns():
    step("1) DNS resolution")
    try:
        ip = socket.gethostbyname(HOST)
        print(f"OK  {HOST} -> {ip}")
        return True
    except Exception as e:
        print(f"FAIL  DNS lookup failed: {e}")
        return False


def check_direct(url):
    step(f"2) Direct GET {url}")
    t0 = time.time()
    try:
        r = requests.get(url, timeout=5, headers=HEADERS)
        dt = time.time() - t0
        print(f"HTTP {r.status_code}  ({dt:.2f}s)")
        try:
            j = r.json()
            print(f"status field: {j.get('status')!r}")
            resp = j.get("response")
            if isinstance(resp, dict):
                print(f"date: {resp.get('date')!r}")
                print(f"prizes: {len(resp.get('prizes', []))} items")
            elif isinstance(resp, list):
                print(f"list length: {len(resp)}")
        except Exception as je:
            print(f"WARN  not valid JSON: {je}")
            print(f"body preview: {r.text[:200]!r}")
        return r.status_code == 200
    except Exception as e:
        print(f"FAIL  {type(e).__name__}: {e}")
        return False


def check_proxy(url):
    step(f"3) Proxy fallback (codetabs) for {url}")
    proxy_url = f"https://api.codetabs.com/v1/proxy/?quest={url}"
    try:
        r = requests.get(proxy_url, timeout=10, headers=HEADERS)
        print(f"HTTP {r.status_code}")
        try:
            j = r.json()
            print(f"status field: {j.get('status')!r}")
        except Exception:
            print(f"body preview: {r.text[:200]!r}")
        return r.status_code == 200
    except Exception as e:
        print(f"FAIL  {type(e).__name__}: {e}")
        return False


def check_list():
    url = f"{API_BASE}/list/1"
    step(f"4) Draw list  {url}")
    try:
        r = requests.get(url, timeout=5, headers=HEADERS)
        j = r.json()
        items = j.get("response", [])[:3]
        for it in items:
            print(f"  - {it.get('id')}  {it.get('date')}")
        return True
    except Exception as e:
        print(f"FAIL  {e}")
        return False


def main():
    date_id = sys.argv[1] if len(sys.argv) > 1 else None
    url = f"{API_BASE}/lotto/{date_id}" if date_id else f"{API_BASE}/latest"

    print(f"Target URL: {url}\n")

    dns_ok = check_dns()
    direct_ok = check_direct(url)
    if not direct_ok:
        check_proxy(url)
    check_list()

    print("\n=== Summary ===")
    print(f"DNS:    {'OK' if dns_ok else 'FAIL'}")
    print(f"Direct: {'OK' if direct_ok else 'FAIL (will use proxy)'}")
    print("\nIf direct fails on your network, the LottoTool already falls back")
    print("to api.codetabs.com proxy automatically. If both fail, the API or")
    print("your egress is genuinely blocked — try a VPN or different network.")


if __name__ == "__main__":
    main()
