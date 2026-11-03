#!/usr/bin/env python3
"""LaunchCrew demo preflight: read-only checks for the demo surface.

Usage: demo-preflight.py [--base-url https://launchcrew.summitsingh.com]

Fetches each public page signed-out and verifies status 200, key text
markers, footer links, and the sitemap. Checks /api/health and
/api/auth/status shape when the API answers. Prints one line per
check and exits nonzero if any check fails. Makes no network calls
besides GET, writes nothing, sends no credentials, and never prints
response bodies or secret values.
"""
import argparse
import json
import sys
import urllib.request

PAGES = [
    ("/", ["Review desk", "/plans", "/privacy", "/terms", "/demo"]),
    ("/plans", ["Plans for every stage of launch", "/privacy", "/terms", "/demo"]),
    ("/privacy", ["Privacy Policy", "Last updated: November 3, 2026", "/terms", "/demo"]),
    ("/terms", ["Terms of Service", "Last updated: November 3, 2026", "/privacy", "/demo"]),
    ("/demo", ["FICTIONAL DEMO", "nothing here is a real business", "/privacy", "/terms"]),
]

SITEMAP_ROUTES = ["/", "/plans", "/privacy", "/terms", "/demo"]

FAILURES = []


def check(name, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail and not ok else ""))
    if not ok:
        FAILURES.append(name)


def get(base, path, timeout=20):
    request = urllib.request.Request(
        base.rstrip("/") + path, method="GET",
        headers={"User-Agent": "LaunchCrew-demo-preflight/1 (+https://launchcrew.summitsingh.com)"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.status, response.read()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="https://launchcrew.summitsingh.com")
    parser.add_argument("--skip-api", action="store_true",
                        help="skip /api checks when only the static web build is served")
    args = parser.parse_args()
    base = args.base_url.rstrip("/")
    for path, markers in PAGES:
        try:
            status, body = get(base, path)
        except Exception as error:
            check("GET " + path, False, type(error).__name__)
            continue
        text = body.decode("utf-8", "replace")
        check("GET " + path + " 200", status == 200, "status=" + str(status))
        for marker in markers:
            check("marker %r on %s" % (marker, path), marker in text)
        check("no em dash on " + path, "\u2014" not in text)
        check("full html on " + path, "<html" in text.lower() and "</html>" in text.lower())
    try:
        status, body = get(base, "/sitemap.xml")
        text = body.decode("utf-8", "replace")
        check("GET /sitemap.xml 200", status == 200, "status=" + str(status))
        for route in SITEMAP_ROUTES:
            check("sitemap lists " + route, (route + "</loc>") in text)
    except Exception as error:
        check("GET /sitemap.xml", False, type(error).__name__)
    try:
        status, body = get(base, "/facts/demo_facts.json")
        check("GET /facts/demo_facts.json 200", status == 200, "status=" + str(status))
        if status == 200:
            parsed = json.loads(body.decode("utf-8"))
            check("demo facts carry claims", isinstance(parsed.get("approved_claims"), list))
    except Exception as error:
        check("GET /facts/demo_facts.json", False, type(error).__name__)
    if args.skip_api:
        print("SKIP /api checks (--skip-api)")
    else:
        try:
            status, body = get(base, "/api/health")
            check("GET /api/health 200", status == 200, "status=" + str(status))
            if status == 200:
                check("health ok", json.loads(body.decode("utf-8")).get("status") == "ok")
        except Exception as error:
            check("GET /api/health", False, type(error).__name__)
        try:
            status, body = get(base, "/api/auth/status")
            check("GET /api/auth/status 200", status == 200, "status=" + str(status))
            if status == 200:
                fields = json.loads(body.decode("utf-8"))
                check("auth providers list", isinstance(fields.get("providers"), list))
                check("auth no secret values",
                      "client_secret" not in body.decode("utf-8").lower())
        except Exception as error:
            check("GET /api/auth/status", False, type(error).__name__)
    print("---")
    if FAILURES:
        print(str(len(FAILURES)) + " failing checks")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
