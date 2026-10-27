"""Nonshipping exact-result pagination proof against the stock runtime."""
from concurrent.futures import ThreadPoolExecutor
import json
import uuid


def run(reports, rpc):
    context = "native-pagination-" + str(uuid.uuid4())
    records = []

    def save(verdict):
        (reports / "listing-checks.json").write_text(json.dumps({
            "verdict": verdict, "submitted": 125, "submissionConcurrency": 8, "pageSize": 37,
            "records": records,
        }, indent=2) + "\n")

    def call(method, params):
        identifier = str(uuid.uuid4())
        status, response = rpc({"jsonrpc": "2.0", "id": identifier, "method": method, "params": params})
        assert status == 200 and isinstance(response, dict) and response.get("id") == identifier, (status, response)
        assert "result" in response and "error" not in response, response
        return response["result"]

    def send(index):
        text = f"Exact paginated result {index}"
        task = call("SendMessage", {"message": {
            "messageId": str(uuid.uuid4()), "contextId": context, "role": "ROLE_USER", "parts": [{"text": text}]},
        })["task"]
        assert task["status"]["state"] == "TASK_STATE_COMPLETED", task
        assert task["status"]["message"]["parts"] == [{"text": text}], task
        assert task["contextId"] == context, task
        return task

    save("RUNNING")
    try:
        with ThreadPoolExecutor(max_workers=8) as executor:
            expected = list(executor.map(send, range(125)))
        assert len({task["id"] for task in expected}) == 125
        expected.sort(key=lambda task: (task["status"]["timestamp"], task["id"]), reverse=True)
        observed, token, seen_tokens = [], "", set()
        while True:
            page = call("ListTasks", {
                "contextId": context, "pageSize": 37, "pageToken": token, "includeArtifacts": True})
            assert page["totalSize"] == 125 and page["pageSize"] == 37, page
            observed.extend(page["tasks"])
            records.append({"case": "page", "count": len(page["tasks"]), "totalSize": page["totalSize"]})
            assert len(observed) <= 125, "Pagination returned duplicate or unexpected tasks"
            token = page["nextPageToken"]
            if not token:
                break
            assert token not in seen_tokens, "A2A page token did not advance"
            seen_tokens.add(token)
        assert observed == expected, "Paginated tasks differ in identity, order, state, history, text or artifacts"
        assert len({task["id"] for task in observed}) == 125
        assert not call("ListTasks", {"contextId": context, "status": "TASK_STATE_FAILED"})["tasks"]
        assert not call("ListTasks", {
            "contextId": context, "statusTimestampAfter": "2999-01-01T00:00:00Z"})["tasks"]
        records.append({"case": "exact-complete-collection", "count": 125, "uniqueIds": 125,
                        "pages": len(seen_tokens) + 1, "filtersPassed": True})
        save("PASS")
    except Exception:
        save("FAIL")
        raise
