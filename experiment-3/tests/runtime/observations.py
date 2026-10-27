"""Bounded observation of eventually indexed engine state, never a success fallback."""
import json
import time


def read_root_variable(request, instance, name, seconds=15):
    deadline = time.monotonic() + seconds
    searches = 0
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError(
                f"Root variable {name} in instance {instance} was absent after {searches} searches "
                f"within {seconds}s")
        status, response = request("/v2/variables/search?truncateValues=false", {
            "filter": {"processInstanceKey": instance, "scopeKey": instance, "name": name}},
            timeout=min(30, remaining))
        searches += 1
        if status != 200:
            raise RuntimeError(f"Variable search failed for {name}: HTTP {status}")
        values = json.loads(response)["items"]
        if values:
            if len(values) != 1:
                raise RuntimeError(f"Expected one root variable: {name}; found {len(values)}")
            return json.loads(values[0]["value"])
        time.sleep(min(0.25, max(0, deadline - time.monotonic())))
