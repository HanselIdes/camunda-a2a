# camunda-a2a

Can BPMN plus Camunda connectors implement the [A2A protocol](https://a2a-protocol.org)? This repository holds three
experiments that answer it in different ways.

| Folder                                 | What it is                                                                                                                                                                                                                                                                                   | Status                                                                  |
| -------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------- |
| [experiment-1](experiment-1/README.md) | An A2A 1.0 JSON-RPC server built from 9 generated BPMN files, 3 DMNs and OOTB connectors only. The official a2a-tck is the acceptance test.                                                                                                                                                  | Passes the TCK at MUST level. Readable only with the generator at hand. |
| [experiment-2](experiment-2/README.md) | One process instance with two AI agents, a client and a server, that talk A2A 1.0 over HTTP through six element templates generated with the connector template generator and run on OOTB connectors.                                                                                        | Runs end to end on c8run. All three test tiers pass (30 tests).         |
| [experiment-3](experiment-3/README.md) | The experiment 2 client and an always-on server as separate diagrams. The customer models only the agent (14 flow nodes); the A2A protocol is a separate diagram deployed next to it, built from A2A 1.0 element templates and OOTB connectors. The official a2a-tck is the acceptance test. | Passes the TCK at MUST level, with push off and with push on.           |

Each folder is self-contained: its own `bpmn/`, `tests/`, `scripts/` and README. Run commands from inside the folder.

These are nonshipping experiments, not a verified Marketplace release. The status rows summarize experimental runs;
they do not establish authenticated deployment or version compatibility. See the
[experiment 3 candidate profiles](experiment-3/README.md#candidate-validation-profiles-not-a-release) for current
evidence and outstanding limitations.

## License and support

See [LICENSE.md](LICENSE.md) for Camunda License 1.0 and the Marketplace community notices. The legal text is reproduced
unchanged from [Camunda Connectors LICENSE.txt at commit 844cb028](https://github.com/camunda/connectors/blob/844cb028a43e2a15d31f5a49e6cb0a9961c0f208/LICENSE.txt).

Upstream-derived material retains its third-party terms. See
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md), including the separately licensed conformance-suite patch.

**Non-production only.** Use is restricted to development, staging, testing, quality assurance, demonstration, and
evaluation, not live or production systems. Confirmation that Camunda can license this independent community repository
remains outstanding. Do not infer licensing compliance, Marketplace eligibility, or production-use permission from these
files.

This is an unmaintained community contribution, not a Camunda-maintained or certified product. The repository issue
tracker is a contact channel, not a maintenance or support commitment. Marketplace eligibility and publication are not
established by the presence of a license or these notices.
