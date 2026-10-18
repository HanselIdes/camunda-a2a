# camunda-a2a

Can BPMN plus Camunda connectors implement the [A2A protocol](https://a2a-protocol.org)? This repository holds three
experiments that answer it in different ways.

| Folder | What it is | Status |
|--------|------------|--------|
| [experiment-1](experiment-1/README.md) | An A2A 1.0 JSON-RPC server built from 9 generated BPMN files, 3 DMNs and OOTB connectors only. The official a2a-tck is the acceptance test. | Passes the TCK at MUST level. Readable only with the generator at hand. |
| [experiment-2](experiment-2/README.md) | One process instance with two AI agents, a client and a server, that talk A2A 1.0 over HTTP through six element templates generated with the connector template generator and run on OOTB connectors. | Runs end to end on c8run. All three test tiers pass (30 tests). |
| [experiment-3](experiment-3/README.md) | The experiment 2 client and an always-on server as separate diagrams. The customer models only the agent (14 flow nodes); the A2A protocol is a separate diagram deployed next to it, built from A2A 1.0 element templates and OOTB connectors. The official a2a-tck is the acceptance test. | Passes the TCK at MUST level, with push off and with push on. |

Each folder is self-contained: its own `bpmn/`, `tests/`, `scripts/` and README. Run commands from inside the folder.
