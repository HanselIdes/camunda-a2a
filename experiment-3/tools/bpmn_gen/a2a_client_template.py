"""A2A-specific Modeler surface over the stock HTTP JSON connector."""
import json


def build(root):
    prior = json.loads((root / "element-templates/a2a-1.0-client.json").read_text())

    def field(name, label, value="", kind="String", condition=None, **extra):
        prop = {
            "id": name, "label": label, "type": kind, "value": value,
            "group": "operation", "binding": {"type": "zeebe:input", "name": name},
        }
        if kind != "Hidden":
            prop.update(feel="optional", constraints={"notEmpty": True})
        if condition:
            prop["condition"] = {"property": "operationId", "oneOf": condition}
        prop.update(extra)
        if prop.get("feel") is None:
            prop.pop("feel", None)
        return prop

    properties = [
        {"type": "Hidden", "value": "io.camunda:http-json:1",
         "binding": {"type": "zeebe:taskDefinition", "property": "type"}},
        field("operationId", "Operation", "sendMessage", kind="Dropdown",
              choices=[
                  {"name": "Fetch Agent Card", "value": "fetchAgentCard"},
                  {"name": "Send message", "value": "sendMessage"},
                  {"name": "Get task", "value": "getTask"},
              ], feel=None),
        field("url", "Agent Card or JSON-RPC URL", description=(
            "Complete HTTPS Agent Card URL for discovery, or the JSONRPC interface URL for task operations. "
            "Direct connector URLs are supported; no path rewriting is required."),
            constraints={"notEmpty": True, "pattern": {
                "value": "^https://[^ /]+/[^ ]*$",
                "message": "Enter the complete HTTPS Agent Card or JSON-RPC URL",
            }}),
        field("apiKey", "Shared API key", "{{secrets.A2A_API_KEY}}",
              condition=["sendMessage", "getTask"], description=(
                  "8.9: {{secrets.A2A_API_KEY}} from the Connector secret store. "
                  "8.10+: =camunda.secrets.A2A_API_KEY from the cluster secret store. "
                  "Sent as X-Api-Key. Never enter a credential value in the diagram.")),
        field("message", "A2A message", kind="Text", condition=["sendMessage"],
              feel="required", description=(
                  "Message context with messageId, role and parts. For a follow-up, include taskId and "
                  "contextId from the server response, never invented identifiers.")),
        field("taskId", "Task ID", condition=["getTask"],
              description="Use the task ID returned by SendMessage or GetTask."),
        field("authentication.type", "", "noAuth", kind="Hidden"),
        field("method", "", '=if operationId = "fetchAgentCard" then "GET" else "POST"', kind="Hidden"),
        field("headers", "", (
            '=if operationId = "fetchAgentCard" then {"A2A-Version": "1.0"} else '
            '{"A2A-Version": "1.0", "Content-Type": "application/json", "X-Api-Key": apiKey}'
        ), kind="Hidden"),
        field("body", "", (
            '=if operationId = "sendMessage" then {jsonrpc: "2.0", id: uuid(), method: "SendMessage", '
            'params: {message: message, configuration: {returnImmediately: true}}} '
            'else {jsonrpc: "2.0", id: uuid(), method: "GetTask", params: {id: taskId}}'
        ), kind="Hidden", condition=["sendMessage", "getTask"]),
        field("readTimeoutInSeconds", "Read timeout (seconds)", "60"),
        {"id": "resultVariable", "label": "Result variable", "type": "String", "group": "output",
         "optional": True, "binding": {"type": "zeebe:taskHeader", "key": "resultVariable"}},
        {"id": "resultExpression", "label": "Result expression", "type": "Text", "feel": "required",
         "group": "output", "value": "={toolCallResult: response.body}",
         "description": "response.body is the Agent Card or complete JSON-RPC response, including errors.",
         "binding": {"type": "zeebe:taskHeader", "key": "resultExpression"}},
        {"id": "errorExpression", "label": "Error expression", "type": "Text", "feel": "required",
         "group": "output", "optional": True,
         "binding": {"type": "zeebe:taskHeader", "key": "errorExpression"}},
        {"id": "retries", "label": "Retries", "type": "String", "value": "1", "group": "output",
         "binding": {"type": "zeebe:taskDefinition", "property": "retries"}},
    ]
    return {
        "$schema": prior["$schema"], "name": "A2A 1.0 Client",
        "id": prior["id"], "version": 3, "icon": prior["icon"],
        "description": (
            "Discover an A2A 1.0 agent, send a message or read a task over authenticated JSON-RPC. "
            "Targets engine and stock Connectors 8.9+; runtime verification pending for 8.9. "
            "Polling is modeled explicitly. No push or streaming. AI Agent Sub-process v2 requires 8.10+."
        ),
        "documentationRef": prior["documentationRef"], "category": prior["category"],
        "appliesTo": prior["appliesTo"], "elementType": prior["elementType"],
        "engines": {"camunda": "^8.9"},
        "groups": [{"id": "operation", "label": "A2A interaction"},
                   {"id": "output", "label": "Response and errors"}],
        "properties": properties,
    }
