# Manual verification

Steps to check the proof of concept by hand, from a fresh clone. Each step names the command and what to expect.

## 0. Prerequisites

Docker (8 GB memory for Docker is enough), Java 21, Maven, Python 3, `c8ctl`, `uv`, `git`, and a local Ollama with the
model pulled:

```bash
ollama pull qwen3-coder-30b-64k      # or set OLLAMA_MODEL to a model that supports tool calling
git clone https://github.com/HanselIdes/camunda-a2a.git && cd camunda-a2a
cp .env.example .env                 # change the ports if they are taken
```

## 1. Start the stack and talk to the agent

```bash
docker compose -p camunda-a2a -f blueprint/docker-compose.yml --env-file .env up -d --wait
scripts/deploy.sh                    # expect: "connectors serve the deployed versions: a2a-card, a2a-rpc"
curl -s localhost:18090/.well-known/agent-card.json | python3 -m json.tool
```

Expect an Agent Card with `supportedInterfaces[0].url` equal to `http://localhost:18090/a2a` and three skills:
`get_current_time`, `convert_temperature`, `capital_of`.

```bash
curl -s localhost:18090/a2a -H 'Content-Type: application/json' -H 'A2A-Version: 1.0' -d '{
  "jsonrpc":"2.0","id":1,"method":"SendMessage",
  "params":{"message":{"messageId":"m-1","role":"ROLE_USER","parts":[{"text":"What is the capital of Japan?"}]}}}'
```

Expect `TASK_STATE_COMPLETED`, a status message naming Tokyo, and a `tool-trace` artifact listing `capital_of`.
The first call after a cold start can take 15 to 30 seconds. If it takes longer than 25 seconds the task comes back as
`TASK_STATE_WORKING`: poll it with `GetTask` using the returned `id`.

Try these as well:

| Request | Expect |
|---------|--------|
| `SendMessage` with text "Please convert a temperature for me." | `TASK_STATE_INPUT_REQUIRED`; send a follow-up with the same `taskId` ("100 celsius to fahrenheit") and get `COMPLETED` |
| `GetTask` with an unknown id | error `-32001` with `ErrorInfo` reason `TASK_NOT_FOUND` |
| `CancelTask` on a completed task | error `-32002` |
| `SendStreamingMessage` | error `-32004` (streaming is not supported) |
| `A2A-Version: 99.0` header | error `-32009` |
| `ListTasks` with `{"context_id":"<a contextId you used>"}` | the tasks of that context, newest first |

## 2. Unit and integration tests

```bash
mvn verify                  # 112 tests: process, DMN, agent with mocked model, card drift, real connectors
mvn -Pollama verify         # 3 tests against the local model; check "Skipped: 0"
```

The first run pulls Docker images. Both commands start their own Camunda containers on random ports.

## 3. The official TCK (MUST level, JSON-RPC)

```bash
export TCK_DIR=$(mktemp -d)/a2a-tck      # the TCK is untrusted downloaded code, keep it out of the repo
tck/run.sh                               # 3 runs on one fresh stack, a reset, a 4th run (about 10 minutes)
```

Expect four `RESULT ... verdict=OK` lines with `failures=0 errors=0 incidents=0`, and `tck/RESULTS.md` rewritten with
the pin (commit `263b9cf` plus PRs #203, #232, #243). To see why the checker exists, open
`reports/run-1/junitreport.xml`: most skips are other bindings or capabilities the card does not declare, and every one
must be matched in `tck/allowed-not-passing.txt`.

Optional, not part of the gate:

```bash
tck/run-extra.sh      # SHOULD and MAY levels: expect "SHOULD: 7 PASS, 0 FAIL" and "MAY: 4 PASS, 0 FAIL"
tck/run-push.sh       # push notifications switched on: expect PUSH-* PASS (CORE-CAP-001 SKIPPED is expected)
```

## 4. Lint, traceability, card drift

```bash
scripts/lint.sh                      # every bpmn/ file: "No issues found"
python3 scripts/trace.py             # "MUST requirements: 114, ... problems: 0" (needs TCK_DIR from step 3)
python3 tools/gen_card.py --check    # "card matches the 3 agent tools"
```

To see the checks catch something, remove a `name` from an element in `bpmn/a2a-card.bpmn` and run `scripts/lint.sh`
(exit 1), or edit a tool's `<bpmn:documentation>` in `bpmn/a2a-task.bpmn` and run the drift check (exit 1). Restore the
file with `git checkout`.

## 5. End to end from a fresh clone

```bash
blueprint/smoke.sh        # own compose project and free ports; expect "smoke test passed" and exit code 0
```

## 6. Demo in a browser with the a2a-inspector

The [a2a-inspector](https://github.com/a2aproject/a2a-inspector) is the A2A project's web UI for connecting to an agent,
reading its card and chatting with it. `demo/` drives it with Playwright, using the same prompts as the tests
(time, capital of Japan, temperature conversion, an agent question with a follow-up).

```bash
demo/run-demo.sh                 # headless; expect "6 passed"; screenshots land in demo/artifacts/
HEADED=1 demo/run-demo.sh        # watch it in a browser window, slowed down
RECORD=1 demo/run-demo.sh        # also record a video per scenario (demo/artifacts/)
```

The script clones the inspector at a pinned commit outside the repo (`INSPECTOR_DIR`), builds and starts it on a free
port, warms the model up, runs the six scenarios and stops the inspector again. It needs the stack from step 1 and
Ollama running. To do it by hand instead: start the inspector as its README describes, open it, enter
`http://localhost:18090` as the Agent Card URL, press Connect, and send "What is the capital of Japan?".

A recording of a full run (30 seconds, all six scenarios) is checked in at
`demo/recordings/camunda-a2a-inspector-demo.mp4`.

What you see, and why:

- The inspector's chat shows each task **artifact** as a bubble. The agent returns its reply as an `answer` artifact
  (or `question` when it needs input) and a `tool-trace` artifact listing the tools it called. The same reply is also in
  the task's status message, which the inspector only shows in its debug console.
- The inspector sends only a `contextId` on a follow-up, not a `taskId`. Our server therefore starts a new task in the
  same context instead of continuing the one waiting for input, which still works because the follow-up is answerable
  on its own. The continuing-task flow is covered by `blueprint/smoke.sh` and the process tests.
- The inspector shows task states in lower case (`completed`), whatever the server sent.
- If the machine runs low on memory the model can be unloaded and reloaded, and a reply then takes minutes. Keep the
  model loaded (`run-demo.sh` does) and close heavy applications if a scenario stalls.

## 7. Both sides in Tasklist on c8run: client process calls the agent

`a2a-client` is the originating process. It is built from the same parts as the server (HTTP JSON connector, user
tasks, forms) and talks to the agent only through the A2A protocol. A person starts it in Tasklist, it reads the Agent
Card, sends `SendMessage`, polls `GetTask` while the remote task works, relays an `INPUT_REQUIRED` question to a person
and shows the answer.

```bash
scripts/c8run-demo.sh            # c8run 8.10.2 on 8080 (engine) and 8086 (connectors), deploys everything, prints URLs
```

1. Open `http://localhost:8080/tasklist/processes` and sign in (c8run default: `demo` / `demo`).
2. Pick **A2A client: ask the agent**, press **Start process**, keep or change the question, submit.
3. Within about 30 seconds a task **Review the result** appears under Tasks. It shows the answer, the tools the agent
   used on the server side, and the A2A task and context ids. Ask "Please convert a temperature for me." instead to get
   **Answer the agent's question** first; your answer goes back as a follow-up on the same A2A task.
4. Follow the token: in Operate (`http://localhost:8080/operate`) open the `a2a-client` instance, then the `a2a-rpc`
   instance for each request and the long-lived `a2a-task` instance (search by the tag `task-<id>` shown in the result).
   The same path as one merged timeline:

```bash
python3 scripts/token-trace.py                    # newest a2a-client instance
python3 scripts/token-trace.py --client <key>     # a specific one
```

The timeline lists, in time order, the client elements (Send message to the agent), the server handler elements
(Parse request, Validate request, Create task instance), the task instance (Mark task working, the tool that ran,
Apply agent response, Publish reply), and the client elements that follow (Read the agent's reply, Review the result).
The server task instance stays active after it answers; that is its terminal state waiting for `GetTask`.

The same flow runs as an automated test: `ClientServerE2ETest` deploys both sides on one cluster with the real
connectors and a stub model, so it needs no Ollama. `OllamaClientServerE2ETest` (`mvn -Pollama verify`) does it with the
local model.

```bash
scripts/c8run-demo.sh stop
```

## 8. Clean up

```bash
docker compose -p camunda-a2a -f blueprint/docker-compose.yml --env-file .env down -v
```

## If something fails

| Symptom | Likely cause |
|---------|--------------|
| `Could not connect to Ryuk` | Only if you override the test settings; the reaper is disabled in `tests/pom.xml` |
| Requests hang or the card returns 404 right after `up` | The connectors runtime has not activated the webhooks yet; `scripts/deploy.sh` waits for it |
| Agent answers `TASK_STATE_FAILED` | Ollama is not reachable from Docker at `host.docker.internal:11434` or the model is missing |
| TCK run reports incidents | Stale stack from earlier experiments; run `down -v` first (the full `tck/run.sh` does this) |
