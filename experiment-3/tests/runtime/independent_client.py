"""Official Python SDK interoperability against the unmodified real-agent assets."""
import asyncio
import importlib.metadata
import json
import os
from pathlib import Path
import socket
import ssl
import time
from unittest.mock import patch
from urllib.parse import urlparse
import uuid

import httpx
from google.protobuf.json_format import MessageToDict, ParseDict

from a2a.client import ClientConfig, ClientFactory
from a2a.types.a2a_pb2 import (
    AgentCard, GetTaskRequest, ListTasksRequest, Message, Part, ROLE_USER, SendMessageRequest,
    TASK_STATE_COMPLETED, TASK_STATE_INPUT_REQUIRED, TASK_STATE_WORKING,
)
from confirmations import data_part


async def main():
    origin = os.environ["PROOF_SDK_CONNECTORS_URL"]
    port = urlparse(origin).port
    key = os.environ["PROOF_A2A_API_KEY"]
    context = ssl.create_default_context(cafile=os.environ["PROOF_SDK_CA"])
    sent = []

    async def authenticate(request):
        if (request.url.scheme != "https" or request.url.port != port
                or request.url.host not in ("127.0.0.1", "host.docker.internal")):
            raise ValueError("SDK attempted to leave the configured trust boundary")
        if request.url.path == "/inbound/a2a":
            assert request.headers.get("A2A-Version") == "1.0", "SDK omitted or changed the protocol version"
            request.headers["X-A2A-Api-Key"] = key
            sent.append({"method": json.loads(request.content)["method"],
                         "protocolVersion": request.headers["A2A-Version"]})

    async with httpx.AsyncClient(verify=context, trust_env=False, timeout=60,
                                event_hooks={"request": [authenticate]}) as http:
        factory = ClientFactory(ClientConfig(streaming=False, polling=True, httpx_client=http))
        client = await factory.create_from_url(origin, relative_card_path="/inbound/a2a-card")

        async def send(text, previous=None, confirmed=False):
            parts = [Part(text=text)]
            if confirmed:
                parts.append(ParseDict(data_part(), Part()))
            message = Message(role=ROLE_USER, message_id=str(uuid.uuid4()), parts=parts)
            if previous is not None:
                message.task_id = previous.id
                message.context_id = previous.context_id
            events = [event async for event in client.send_message(SendMessageRequest(message=message))]
            assert len(events) == 1 and events[0].HasField("task"), "Expected SDK Task response"
            task = events[0].task
            deadline = time.monotonic() + 300
            while task.status.state == TASK_STATE_WORKING:
                if time.monotonic() >= deadline:
                    raise TimeoutError("SDK polling deadline expired")
                await asyncio.sleep(1)
                task = await client.get_task(GetTaskRequest(id=task.id))
            return task

        waiting = await send("Please review a synthetic card dispute.")
        assert waiting.status.state == TASK_STATE_INPUT_REQUIRED, waiting.status
        completed = await send(
            "49.95 USD was charged twice by Northwind Electronics for one order costing 49.95 USD.",
            waiting, confirmed=True)
        assert completed.id == waiting.id and completed.context_id == waiting.context_id
        assert completed.status.state == TASK_STATE_COMPLETED, completed.status
        assert len(completed.history) == 4, "SDK follow-up history differs"
        artifact = next(a for a in completed.artifacts if a.name == "reconciliation")
        data = MessageToDict(artifact.parts[0].data)
        assert data == {
            "merchant": "Northwind Electronics", "currency": "USD", "chargeAmounts": [49.95, 49.95],
            "expectedAmount": 49.95, "paidAmount": 99.9, "overchargeAmount": 49.95,
            "matchingAmounts": True, "recommendation": "REQUEST_HUMAN_REVIEW", "syntheticOnly": True
        }, data
        fetched = await client.get_task(GetTaskRequest(id=completed.id))
        assert fetched == completed, "SDK polling changed terminal evidence"
        listed = await client.list_tasks(ListTasksRequest(context_id=completed.context_id, include_artifacts=True))
        assert [t.id for t in listed.tasks] == [completed.id], "SDK context listing leaked or omitted tasks"
        discovery = await http.get(origin + "/inbound/a2a-card")
        discovery.raise_for_status()
        patch_negotiation = []
        for version in ("1.0", "1.0.2", "1.0.999"):
            card = ParseDict(discovery.json(), AgentCard())
            card.supported_interfaces[0].protocol_version = version
            negotiated = factory.create(card)
            assert await negotiated.get_task(GetTaskRequest(id=completed.id)) == completed
            patch_negotiation.append({"advertisedVersion": version, "sameTerminalTask": True,
                                      "requestVersion": sent[-1]["protocolVersion"]})
        await client.close()
    result = {"sdk": "a2a-sdk", "version": importlib.metadata.version("a2a-sdk"),
              "transport": "JSONRPC", "protocol": "1.0", "tlsCertificateVerified": True,
              "checks": ["explicit discovery", "SDK transport negotiation", "nonblocking send", "polling",
                         "input-required", "numeric-leading follow-up", "four-message history",
                         "exact reconciliation artifact", "terminal retrieval", "context-filtered list"],
              "authenticatedRequests": len(sent), "requestVersions": sent,
              "patchNegotiation": patch_negotiation, "verdict": "PASS"}
    assert result["version"] == "1.2.3", "Independent SDK version differs from pinned manifest"
    Path(os.environ["PROOF_SDK_REPORT"]).write_text(json.dumps(result, indent=2) + "\n")
    print("Independent a2a-sdk 1.2.3 discovery/send/follow-up/get/list and exact real-model result: PASS", flush=True)


if __name__ == "__main__":
    original = socket.getaddrinfo
    port = urlparse(os.environ["PROOF_SDK_CONNECTORS_URL"]).port

    def resolve(host, service, *args, **kwargs):
        if host in ("host.docker.internal", b"host.docker.internal") and str(service) == str(port):
            host = "127.0.0.1"
        return original(host, service, *args, **kwargs)

    with patch.object(socket, "getaddrinfo", resolve):
        asyncio.run(main())
