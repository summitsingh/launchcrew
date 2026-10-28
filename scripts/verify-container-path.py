#!/usr/bin/env python3
"""Keyless container path check through the real API and web proxy.

Exercises the actual demo path with no model calls and no auth: health
direct and through the Next rewrite proxy, agent list, run creation,
receipt read, approval gate (export refused before approval), approval,
export, and queue listing. Only status codes, run ids, and counts are
printed. No request bodies, headers, environment, or secrets are logged.
Writes a small evidence file to .local/container-path-evidence.json.
"""
import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

TIMEOUT = 10
IDEA = "Vegan leather wallet, $49, for Austin commuters, launch on Instagram"


def call(base, method, path, body=None):
    data = None
    headers = {"accept": "application/json"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["content-type"] = "application/json"
    request = urllib.request.Request(base + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            raw = response.read().decode("utf-8")
            return response.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as error:
        try:
            payload = json.loads(error.read().decode("utf-8"))
        except Exception:
            payload = None
        return error.code, payload


def need(condition, label):
    if not condition:
        print("FAIL: " + label)
        raise SystemExit(1)
    print("PASS: " + label)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-base", required=True)
    parser.add_argument("--web-base", required=True)
    args = parser.parse_args()
    api = args.api_base.rstrip("/")
    web = args.web_base.rstrip("/")

    status, health = call(api, "GET", "/api/health")
    need(status == 200 and health.get("status") == "ok", "direct API health HTTP 200 status ok")
    need(health.get("auth") == "disabled_demo", "direct API health auth disabled_demo")
    need(health.get("approval_by") == "demo_placeholder", "direct API approval_by demo_placeholder")

    status, proxied = call(web, "GET", "/api/health")
    need(status == 200 and proxied.get("status") == "ok", "web proxy API health HTTP 200 status ok")
    need(proxied.get("auth") == "disabled_demo", "web proxy health auth disabled_demo")

    status, agents = call(web, "GET", "/api/agents")
    need(status == 200 and isinstance(agents, list) and agents, "agent list non-empty through proxy")
    names = [entry.get("name") for entry in agents if isinstance(entry, dict) and entry.get("name")]
    maker = next((name for name in names if name.lower() == "maker"), names[0])
    print("PASS: using agent " + maker)

    status, run = call(web, "POST", "/api/runs", {"idea": IDEA, "agent_name": maker})
    need(status == 201, "create plain run HTTP 201 through proxy")
    run_id = run.get("run_id", "")
    need(bool(run_id) and run.get("approval_state") == "pending_approval", "plain run pending_approval with id")
    print("PASS: plain run " + run_id)

    status, reread = call(api, "GET", "/api/runs/" + run_id)
    need(status == 200 and reread.get("run_id") == run_id, "receipt read matches through direct API")

    status, seeded = call(web, "POST", "/api/runs", {"idea": IDEA, "agent_name": maker, "seed_unverified_claim": True})
    need(status == 201, "create seeded run HTTP 201 through proxy")
    seed_id = seeded.get("run_id", "")
    need(bool(seed_id), "seeded run has id")
    v1 = (seeded.get("checker_v1") or {}).get("blocked_count", 0)
    need(isinstance(v1, int) and v1 >= 1, "seeded run blocked in v1")
    print("PASS: seeded run " + seed_id)

    status, _ = call(web, "POST", "/api/runs/" + seed_id + "/export", {})
    need(status == 422, "export before approval refused HTTP 422")

    status, approved = call(web, "POST", "/api/runs/" + seed_id + "/approve", {})
    need(status == 200 and approved.get("approval_state") == "approved_for_export", "seeded run approved for export")
    need(bool(approved.get("approvals")), "seeded run carries approval record")

    status, pack = call(web, "POST", "/api/runs/" + seed_id + "/export", {})
    need(status == 200, "seeded export HTTP 200 after approval")
    need(pack.get("approval_state") == "approved_for_export", "exported pack approved_for_export")
    need((pack.get("summary") or {}).get("submit_attempted") is False, "exported pack submit_attempted false")

    status, queue = call(web, "GET", "/api/queue")
    need(status == 200 and isinstance(queue, list), "queue lists through proxy")
    queued = {entry.get("run_id") for entry in queue if isinstance(entry, dict)}
    need(run_id in queued and seed_id in queued, "both runs present in queue")

    evidence = {"api_health": health, "proxy_health": proxied, "agent": maker,
                "plain_run_id": run_id, "seeded_run_id": seed_id,
                "seeded_v1_blocked": v1, "export_submit_attempted": False}
    try:
        Path(".local").mkdir(exist_ok=True)
        Path(".local/container-path-evidence.json").write_text(
            json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    except OSError:
        pass
    print("PASS: container path complete, no model calls, nothing submitted")


if __name__ == "__main__":
    main()
