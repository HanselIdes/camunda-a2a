#!/usr/bin/env python3
"""Follows one A2A conversation across the client and the server process instances, as one timeline.

Usage: scripts/token-trace.py [--rest http://localhost:8080] [--client <processInstanceKey>] [--wait-seconds N]

Without --client it takes the newest a2a-client instance. The timeline merges the element instances of
1. the client instance (a2a-client),
2. the server handler instances (a2a-rpc) that started while the conversation was running, and
3. the long-lived server task instance (a2a-task) found through its `task-<taskId>` tag.
Handler instances carry no tag, so they are matched by time window. Run it while nothing else talks to the server.
"""
import argparse
import json
import re
import sys
import time
import urllib.request


def call(rest, path, body):
    req = urllib.request.Request(rest + path, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def elements(rest, key):
    out = call(rest, "/v2/element-instances/search", {
        "filter": {"processInstanceKey": str(key)}, "sort": [{"field": "startDate", "order": "ASC"}],
        "page": {"limit": 1000}})
    return out["items"]


def variable(rest, key, name):
    items = call(rest, "/v2/variables/search", {"filter": {"processInstanceKey": str(key), "name": name}})["items"]
    return json.loads(items[0]["value"]) if items else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rest", default="http://localhost:8080")
    ap.add_argument("--client")
    ap.add_argument("--wait-seconds", type=int, default=0, help="wait for the client instance to finish")
    a = ap.parse_args()
    rest = a.rest.rstrip("/")

    if a.client:
        inst = call(rest, "/v2/process-instances/search", {"filter": {"processInstanceKey": a.client}})["items"]
    else:
        inst = call(rest, "/v2/process-instances/search", {
            "filter": {"processDefinitionId": "a2a-client"}, "sort": [{"field": "startDate", "order": "DESC"}],
            "page": {"limit": 1}})["items"]
    if not inst:
        sys.exit("no a2a-client instance found")
    client = inst[0]
    key = client["processInstanceKey"]
    deadline = time.time() + a.wait_seconds
    while client["state"] == "ACTIVE" and time.time() < deadline:
        time.sleep(2)
        client = call(rest, "/v2/process-instances/search", {"filter": {"processInstanceKey": key}})["items"][0]

    rows = [(e["startDate"], "client  a2a-client", e) for e in elements(rest, key)]
    reply = variable(rest, key, "reply") or {}
    task_id = reply.get("taskId")
    start = client["startDate"]
    end = client.get("endDate") or "9999"

    handlers = call(rest, "/v2/process-instances/search", {
        "filter": {"processDefinitionId": "a2a-rpc", "startDate": {"$gte": start}},
        "sort": [{"field": "startDate", "order": "ASC"}], "page": {"limit": 200}})["items"]
    for h in handlers:
        if h["startDate"] > end:
            continue
        ctx = variable(rest, h["processInstanceKey"], "ctx") or {}
        method = ctx.get("method") or re.sub(r".*method\W+(\w+).*", r"\1", json.dumps(ctx))
        for e in elements(rest, h["processInstanceKey"]):
            rows.append((e["startDate"], "server  a2a-rpc (%s)" % method, e))

    if task_id:
        tasks = call(rest, "/v2/process-instances/search", {"filter": {"tags": ["task-" + task_id]}})["items"]
        for t in tasks:
            for e in elements(rest, t["processInstanceKey"]):
                rows.append((e["startDate"], "server  a2a-task", e))

    rows.sort(key=lambda r: r[0])
    print("client instance %s  state %s  A2A task %s" % (key, client["state"], task_id))
    print("%-12s %-30s %-34s %-22s %s" % ("time (UTC)", "process", "element", "type", "state"))
    skip = {"PROCESS", "SUB_PROCESS", "EVENT_SUB_PROCESS", "AD_HOC_SUB_PROCESS"}
    shown = 0
    for when, proc, e in rows:
        if e["type"] in skip and e["type"] != "SUB_PROCESS" and e["type"] != "AD_HOC_SUB_PROCESS":
            continue
        shown += 1
        print("%-12s %-30s %-34s %-22s %s" % (when[11:23], proc, (e.get("elementName") or e["elementId"])[:34],
                                              e["type"], e["state"]))
    if not shown:
        sys.exit("no element instances found")


if __name__ == "__main__":
    main()
