# camunda-a2a

Can BPMN plus Camunda connectors implement the [A2A protocol](https://a2a-protocol.org)? This repository holds two
experiments that answer it in different ways.

| Folder | What it is | Status |
|--------|------------|--------|
| [experiment-1](experiment-1/README.md) | An A2A 1.0 JSON-RPC server built from 9 generated BPMN files, 3 DMNs and OOTB connectors only. The official a2a-tck is the acceptance test. | Passes the TCK at MUST level. Readable only with the generator at hand. |
| experiment-2 | One diagram with two pools, a client agent and a server agent, that talk A2A 1.0 through custom element templates layered on OOTB connectors. | In progress. |

Each folder is self-contained: its own `bpmn/`, `tests/`, `scripts/` and README. Run commands from inside the folder.
