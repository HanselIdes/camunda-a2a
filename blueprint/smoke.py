#!/usr/bin/env python3
"""Smoke test of a running camunda-a2a stack against the real local model.

  python3 blueprint/smoke.py <public base url>      e.g. http://localhost:18090

Checks: the Agent Card lists the three agent tools as skills (and the card has not drifted from the tools),
"what time is it?" reaches COMPLETED within 180 s through GetTask polling with get_current_time in the tool
trace, and an agent INPUT_REQUIRED round trip succeeds within 3 attempts.
"""
import json
import os
import subprocess
import sys
import time
import urllib.request
import uuid

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
TOOLS = ["get_current_time", "convert_temperature", "capital_of"]


def http(url, body=None, headers=None, timeout=120):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers=headers or {}, method="POST" if data else "GET")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def rpc(base, method, params):
    return http(base + "/a2a", {"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
                {"Content-Type": "application/json", "A2A-Version": "1.0"})


def message(text, task_id=None):
    m = {"messageId": str(uuid.uuid4()), "role": "ROLE_USER", "parts": [{"text": text}]}
    if task_id:
        m["taskId"] = task_id
    return {"message": m}


def ask(base, text, task_id=None, deadline=180):
    """SendMessage, then poll GetTask while the task is still working, like a real client."""
    start = time.time()
    task = rpc(base, "SendMessage", message(text, task_id))["result"]["task"]
    while task["status"]["state"] in ("TASK_STATE_SUBMITTED", "TASK_STATE_WORKING"):
        if time.time() - start > deadline:
            raise SystemExit("FAIL: task %s still %s after %ds" % (task["id"], task["status"]["state"], deadline))
        time.sleep(2)
        task = rpc(base, "GetTask", {"id": task["id"]})["result"]
    return task, time.time() - start


def tools_used(task):
    used = []
    for a in task.get("artifacts", []):
        if a.get("name") == "tool-trace":
            for call in a["parts"][0]["data"]["toolCalls"]:
                used.append(call["name"])
    return used


def check(cond, message_):
    print(("ok   " if cond else "FAIL ") + message_)
    if not cond:
        raise SystemExit(1)


def main(base):
    card = http(base + "/.well-known/agent-card.json")
    check([s["id"] for s in card["skills"]] == TOOLS, "Agent Card lists the three agent tools as skills")
    check(card["supportedInterfaces"][0]["url"] == base + "/a2a", "Agent Card interface URL is the public URL")
    drift = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "gen_card.py"), "--check"],
                           capture_output=True, text=True)
    check(drift.returncode == 0, "card matches the card generated from the tools (drift check): " + drift.stdout.strip())

    task, seconds = ask(base, "what time is it?")
    check(task["status"]["state"] == "TASK_STATE_COMPLETED", "time question reaches COMPLETED in %.0fs" % seconds)
    check("get_current_time" in tools_used(task), "get_current_time is in the tool trace %s" % tools_used(task))

    waiting = None
    for attempt in range(1, 4):
        task, seconds = ask(base, "Please convert a temperature for me.")
        print("     attempt %d: %s" % (attempt, task["status"]["state"]))
        if task["status"]["state"] == "TASK_STATE_INPUT_REQUIRED":
            waiting = task
            break
    check(waiting is not None, "agent asked for input within 3 attempts")
    done, seconds = ask(base, "100 celsius to fahrenheit", waiting["id"])
    check(done["status"]["state"] == "TASK_STATE_COMPLETED", "follow-up completes the task in %.0fs" % seconds)
    check("convert_temperature" in tools_used(done), "convert_temperature is in the tool trace %s" % tools_used(done))
    print("smoke test passed")


if __name__ == "__main__":
    main(sys.argv[1].rstrip("/"))
