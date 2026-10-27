"""Verify literal model input through the shipped real-agent task and follow-up paths."""
import json
import time
import uuid

from observations import read_root_variable

CASES = (
    ("numeric", "49.95 USD: synthetic diagnostic only. Please ask for missing details."),
    ("quotes", 'Synthetic diagnostic only: a merchant label says "example". Please ask for missing details.'),
    ("backslashes", r"Synthetic diagnostic only: reference C:\lab\order\n.txt. Please ask for missing details."),
    ("newlines", "Synthetic diagnostic only:\nfirst line\nsecond line. Please ask for missing details."),
    ("controls", "Synthetic diagnostic only: A" + "".join(chr(n) for n in range(32))
     + "\u007fZ. Please ask for missing details."),
    ("expression", '={"synthetic":true}'),
)


def assert_literal_input(expected, request, agent):
    assert request["message"]["parts"][0]["text"] == expected, "Original task input changed"
    texts = [content["text"] for message in agent["context"]["conversation"]["messages"]
             if message["role"] == "user" for content in message.get("content", [])
             if content.get("type") == "text"]
    assert texts == [expected], ("Model input differs from the original text", expected, texts)
    return texts[0]


def run(reports, rpc, request, await_task):
    records = []
    report = reports / "literal-model-inputs.json"
    for label, text in CASES:
        message = {"jsonrpc": "2.0", "id": "literal-" + label, "method": "SendMessage",
                   "params": {"message": {"messageId": str(uuid.uuid4()), "role": "ROLE_USER",
                                          "parts": [{"text": text}]}}}
        status, response = rpc(message)
        assert status == 200 and "result" in response, (label, status, response)
        task = await_task(response)
        deadline = time.monotonic() + 30
        while True:
            status, body = request("/v2/process-instances/search",
                                   {"filter": {"tags": ["task-" + task["id"]]}})
            assert status == 200, (label, status, body)
            items = json.loads(body)["items"]
            if len(items) == 1:
                business = items[0]["processInstanceKey"]
                break
            if time.monotonic() >= deadline:
                raise TimeoutError("Unique literal-input business task was not indexed")
            time.sleep(0.5)
        req = read_root_variable(request, business, "req")
        agent = read_root_variable(request, business, "agent")
        record = {"case": label, "inputText": text, "requestRoot": req, "agent": agent, "task": task}
        records.append(record)
        report.write_text(json.dumps({"records": records, "verdict": "RUNNING"}, indent=2) + "\n")
        record["modelUserText"] = assert_literal_input(text, req, agent)
        record["verbatim"] = True
        record["requiredState"] = "TASK_STATE_INPUT_REQUIRED"
        record["semanticStateMatches"] = task["status"]["state"] == record["requiredState"]
        complete = len(records) == len(CASES)
        report.write_text(json.dumps({
            "records": records,
            "literalInputVerdict": "PASS" if complete else "RUNNING",
            "semanticVerdict": "FAIL" if not record["semanticStateMatches"] else
                               "PASS" if complete else "RUNNING",
            "verdict": "FAIL" if not record["semanticStateMatches"] else
                       "PASS" if complete else "RUNNING",
        }, indent=2) + "\n")
        assert record["semanticStateMatches"], (label, task)
    print("Six actual model inputs preserve numeric/quote/backslash/newline/control/expression text: PASS",
          flush=True)
