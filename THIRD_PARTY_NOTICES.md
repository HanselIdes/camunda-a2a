# Third-party notices

## A2A conformance-suite patch

`experiment-3/tck/patches/tck-pr-stack.patch` contains modified upstream source excerpts
from [a2aproject/a2a-tck](https://github.com/a2aproject/a2a-tck/tree/263b9cfaf16a554bdfb166a7ba5b67716e946349).
The base is commit `263b9cfaf16a554bdfb166a7ba5b67716e946349`; the patch combines upstream
pull requests 203, 232 and 243, with the conflicting imports merged locally.
The changes affect 21 files, including protocol specifications and conformance checks.
The original source and its contributors retain their rights.

This upstream-derived material is covered by **Apache License 2.0**, not superseded by
the repository's Camunda License. A copy of the exact upstream license is included in
[licenses/Apache-2.0.txt](licenses/Apache-2.0.txt).
The pinned upstream tree contains no `NOTICE` file. Applying the patch to the pinned
checkout preserves the original source files and their existing notices.
Keep these notices and the Apache license when redistributing the patch.

The conformance suite and patch are contributor verification tools, not deployable
blueprint resources. They must not be included in the Modeler resource-import bundle.

## Separately installed dependencies

Camunda engine, stock Connectors, Modeler, Elasticsearch, model providers, Java/Maven
test dependencies, and the conformance runner are installed separately. Refer to their
own distribution licenses; they are not redistributed as binaries in the blueprint.
Calling a stock connector's task type or recording its element-template identifier
does not change that dependency's license.

The included HTTP JSON template version 12 comes from Camunda Connectors commit
`844cb028a43e2a15d31f5a49e6cb0a9961c0f208`, under
`connectors/http/rest/element-templates/versioned/http-json-connector-12.json`.
That module's license is Apache 2.0, identical to the retained license above.
The template's embedded icon is omitted; the other fields retain the upstream configuration.
The upstream attribution is retained in
[licenses/camunda-connectors-NOTICE.txt](licenses/camunda-connectors-NOTICE.txt).

The AI Agent template version 5 is imported from the immutable upstream URL, not copied
into this repository's resource bundle. Its `connectors/agentic-ai/LICENSE.txt` is a
separate proprietary-license notice referring to Camunda Self-Managed Free/Enterprise
Edition terms. The root repository license does not replace those terms or establish
redistribution authority for that module. Existing authorized non-production runtime
access is not a blanket redistribution permission.

Candidate demo diagrams use these stock templates for connector configuration, with
embedded template icons omitted.
The archived experiments and their old icons/templates are not release resources.

These notices do not establish Camunda licensing authority for this independent
repository, production-use permission, Marketplace approval, or a support obligation.
