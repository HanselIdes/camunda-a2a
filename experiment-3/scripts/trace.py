#!/usr/bin/env python3
"""Requirement traceability: every MUST requirement of the pinned a2a-tck must appear in the README matrix
with at least one test that exists, or with an N/A reason.

  python3 scripts/trace.py            verify (exit 0 when complete)
  python3 scripts/trace.py --update   regenerate the matrix inside README.md from the table below, then verify

The MUST ids come from tck.requirements.registry.get_must_requirements() of the pinned TCK (no regex over
the TCK sources). The TCK lives outside this repo: TCK_DIR (default $TMPDIR/camunda-a2a-3-tck) is prepared
by tck/run.sh. The script re-runs itself with the TCK's own interpreter, so it needs no TCK on sys.path.
"""
import os
import re
import subprocess
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
README = os.path.join(ROOT, "README.md")
TESTS = os.path.join(ROOT, "tests", "src", "test", "java", "dev", "hansel", "a2a", "three")
BEGIN, END = "<!-- trace:begin -->", "<!-- trace:end -->"
NA_REASONS = ["capability-not-declared", "other-binding", "client-side", "not-exercised"]

# id -> (BPMN/DMN elements, tests as Class#method). Requirements missing here must have an N/A reason below.
IMPLEMENTED = {
    "CORE-SEND-001": ("a2a-rpc: PrepareNewTask, CreateTask, AwaitNewTask", ["TaskTest#completeTaskReturnsCompletedTaskWithStatusMessage"]),
    "CORE-SEND-002": ("a2a-rpc: CheckFollowUp (terminal state)", ["TaskTest#terminalTaskAnswersGetAndRejectsCancelAndSend"]),
    "CORE-SEND-003": ("a2a-validate rule 9", ["DmnTest#validatesRequests", "ValidationTest#invalidParams"]),
    "CORE-GET-001": ("a2a-rpc: FindTask, ReadTask (a2a-await), BuildTaskView", ["TaskTest#terminalTaskAnswersGetAndRejectsCancelAndSend", "AgentTest#taskAnswersGetTaskAndCancelWhileTheAgentIsWorking"]),
    "CORE-GET-002": ("a2a-rpc: BuildNotFound", ["TaskTest#unknownTaskIsNotFoundForGetCancelAndFollowUp", "WebhookIntegrationTest#unknownTaskIsNotFoundBecauseNoInstanceCarriesItsTag"]),
    "CORE-LIST-001": ("a2a-rpc: SearchTasks, ReadTasks, BuildTaskList", ['ListTasksTest#listsTheTasksOfAContextNewestFirstWithoutArtifacts', 'ListTasksTest#unknownContextAndOddContextIdsAreHandled']),
    "CORE-LIST-002": ('a2a-rpc: BuildTaskList (offset cursor in pageToken)', ['ListTasksTest#pagesWithCursorTokens']),
    "CORE-LIST-003": ('a2a-rpc: BuildTaskList (sort by status timestamp, descending)', ['ListTasksTest#listsTheTasksOfAContextNewestFirstWithoutArtifacts']),
    "CORE-LIST-004": ('a2a-rpc: BuildTaskList (empty nextPageToken on the last page)', ['ListTasksTest#pagesWithCursorTokens']),
    "CORE-LIST-005": ('a2a-rpc: BuildTaskList (artifacts dropped unless includeArtifacts)', ['ListTasksTest#listsTheTasksOfAContextNewestFirstWithoutArtifacts']),
    "PUSH-CREATE-001": ("a2a-rpc: PreparePushOp, CreateConfig or ReplaceConfig (one cluster variable per config)", ['PushTest#configurationOperationsWorkOnCompletedAndWaitingTasks']),
    "PUSH-CREATE-002": ("a2a-rpc: AwaitConfig, ReadConfigs (cluster variables outlive the task process)", ['PushTest#configurationOperationsWorkOnCompletedAndWaitingTasks', 'PushIntegrationTest#configurationOperationsWorkThroughTheRealConnectors']),
    "PUSH-GET-001": ("a2a-rpc: ReadConfigs, PreparePushOp", ['PushTest#configurationOperationsWorkOnCompletedAndWaitingTasks']),
    "PUSH-GET-002": ("a2a-rpc: PreparePushOp (unknown config id)", ['PushTest#configurationOperationsWorkOnCompletedAndWaitingTasks']),
    "PUSH-LIST-001": ("a2a-rpc: ReadConfigs, PreparePushOp", ['PushTest#configurationOperationsWorkOnCompletedAndWaitingTasks']),
    "PUSH-DEL-001": ("a2a-rpc: DeleteConfig, AwaitConfig", ['PushTest#configurationOperationsWorkOnCompletedAndWaitingTasks']),
    "PUSH-DEL-002": ("a2a-rpc: PreparePushOp (no write when the config is gone), ConfigGone", ['PushTest#configurationOperationsWorkOnCompletedAndWaitingTasks']),
    "PUSH-DELIVER-001": ('a2a-push-notify: DeliverNotification (Authorization header)', ['PushTest#configGivenWithTheFirstMessageIsDeliveredOnEveryStateChange', 'PushIntegrationTest#cardDeclaresPushAndDeliveryReachesTheHostWithTheConfiguredAuthentication']),
    "PUSH-DELIVER-002": ("a2a-task-update: FindPushConfigs, StartPushDelivery; a2a-rpc: FindCancelPush; a2a-push-notify", ['PushTest#configGivenWithTheFirstMessageIsDeliveredOnEveryStateChange', 'PushTest#cancelIsDeliveredToo']),
    "PUSH-DELIVER-003": ("a2a-task-update: StartPushDelivery (payload {task})", ['PushTest#configGivenWithTheFirstMessageIsDeliveredOnEveryStateChange']),
    "CORE-CANCEL-001": ("a2a-rpc: MarkCanceled, StoreCanceled, CancelAgent, AwaitCanceled", ["TaskTest#cancelInputRequiredTaskAndCancelAgainFails"]),
    "CORE-CANCEL-002": ("a2a-rpc: Cancelable, BuildNotCancelable", ["TaskTest#terminalTaskAnswersGetAndRejectsCancelAndSend", "TaskTest#cancelInputRequiredTaskAndCancelAgainFails"]),
    "CORE-CANCEL-003": ("a2a-rpc: BuildNotFound", ["TaskTest#unknownTaskIsNotFoundForGetCancelAndFollowUp"]),
    "CORE-EXECUTION-MODE-001": ("a2a-rpc: AwaitNewTask, AwaitFollowUp (until a settled state)", ["TaskTest#completeTaskReturnsCompletedTaskWithStatusMessage", "AgentTest#sendMessageReturnsWorkingStateWhenTheAgentIsSlow"]),
    "CORE-EXECUTION-MODE-002": ("a2a-rpc: AwaitNewTask (until the task is visible)", ["TaskTest#returnImmediatelyAnswersBeforeTheWorkAndTheTaskCompletesAnyway"]),
    "CORE-ERR-001": ("a2a-validate; a2a-rpc: BuildValidationError", ["ValidationTest#unknownMethodAndInvalidRequest", "ValidationTest#capabilityErrors"]),
    "CORE-ERR-002": ("a2a-validate rules 8 and 10", ["ValidationTest#invalidParams", "TaskTest#noIncidentsAfterMalformedInput"]),
    "CORE-CAP-001": ("a2a-validate rule 6", ["ValidationTest#capabilityErrors", "DmnTest#validatesRequests"]),
    "CORE-CAP-002": ("a2a-validate rule 4", ["ValidationTest#capabilityErrors", "DmnTest#validatesRequests"]),
    "CORE-CAP-003": ("a2a-validate rule 5", ["ValidationTest#capabilityErrors", "DmnTest#validatesRequests"]),
    "CORE-MULTI-001a": ("a2a-rpc: PrepareNewTask", ["TaskTest#contextIdIsGeneratedEchoedAndChecked"]),
    "CORE-MULTI-002a": ("a2a-rpc: PrepareNewTask (echoes the client contextId)", ["TaskTest#contextIdIsGeneratedEchoedAndChecked"]),
    "CORE-MULTI-003": ("a2a-rpc: PrepareNewTask (uuid)", ["TaskTest#taskIdsAreUnique"]),
    "CORE-MULTI-004": ("a2a-rpc: FindTask, BuildNotFound", ["TaskTest#unknownTaskIsNotFoundForGetCancelAndFollowUp"]),
    "CORE-MULTI-005": ("a2a-rpc: CorrelateFollowUp; agent: FollowUp (message a2a-send)", ["TaskTest#inputRequiredThenFollowUpCompletes"]),
    "CORE-MULTI-006": ("a2a-rpc: CheckFollowUp, BuildFollowUpError", ["TaskTest#contextIdIsGeneratedEchoedAndChecked"]),
    "CORE-HIST-002": ("a2a-rpc: BuildTaskView, BuildNewTaskResponse (historyLength projection)", ["TaskTest#historyLengthLimitsHistoryOnGetTask"]),
    "DM-TASK-001": ("a2a-rpc: PrepareNewTask; a2a-task-update: ApplyOutcome", ["TaskTest#completeTaskReturnsCompletedTaskWithStatusMessage"]),
    "DM-TASK-002": ("a2a-task-update: ApplyOutcome; a2a-rpc: MarkCanceled; agent: FollowUp output mapping", ["TaskTest#cancelInputRequiredTaskAndCancelAgainFails", "AgentTest#agentFailureFailsTheTask"]),
    "DM-MSG-001": ("a2a-task-update: ApplyOutcome (agent messages)", ["TaskTest#completeTaskReturnsCompletedTaskWithStatusMessage", "ValidationTest#directMessageResponse"]),
    "DM-MSG-002": ("a2a-rpc: PrepareNewTask (ROLE_USER); a2a-task-update: ApplyOutcome (ROLE_AGENT)", ["TaskTest#completeTaskReturnsCompletedTaskWithStatusMessage"]),
    "DM-PART-001": ("TCK fixture: ApplyScenario artifact parts", ["TaskTest#artifactsAreAttachedByMessageIdPrefix"]),
    "DM-ART-001": ("TCK fixture: ApplyScenario; a2a-task-update: ApplyOutcome", ["TaskTest#artifactsAreAttachedByMessageIdPrefix"]),
    "DM-STATUS-001": ("a2a-task-update: ApplyOutcome (status object)", ["TaskTest#completeTaskReturnsCompletedTaskWithStatusMessage"]),
    "DM-SERIAL-001": ("every FEEL response builder uses camelCase keys", ["TaskTest#artifactsAreAttachedByMessageIdPrefix"]),
    "DM-SERIAL-002": ("TASK_STATE_* and ROLE_* strings", ["TaskTest#completeTaskReturnsCompletedTaskWithStatusMessage"]),
    "DM-SERIAL-003": ("timestamps built as UTC strings ending in Z", ["TaskTest#completeTaskReturnsCompletedTaskWithStatusMessage"]),
    "DM-SERIAL-004": ("null keys are dropped from every object", ["TaskTest#completeTaskReturnsCompletedTaskWithStatusMessage"]),
    "CARD-DISC-001": ("a2a-card: A2A 1.0 Server: Agent Card template", ["CardTest#cardProcessEndsRightAway", "WebhookIntegrationTest#agentCardIsServedWithThePublicUrlAndTheToolSkills"]),
    "CARD-PROTO-001": ("a2a-card: supportedInterfaces from A2A_PUBLIC_URL", ["WebhookIntegrationTest#agentCardIsServedWithThePublicUrlAndTheToolSkills"]),
    "CARD-PROTO-002": ("a2a-card: supportedInterfaces from A2A_PUBLIC_URL", ["WebhookIntegrationTest#agentCardIsServedWithThePublicUrlAndTheToolSkills"]),
    "CARD-STRUCT-001": ("a2a-card: response expression of the card start event", ["TemplatesIntegrationTest#agentCardIsServedOnGetWithTheConfiguredEndpointAndCapabilities", "CardTest#committedCardMatchesTheCardGeneratedFromTheAgentTools"]),
    "BIND-FIELD-001": ("a2a-card: supportedInterfaces", ["WebhookIntegrationTest#agentCardIsServedWithThePublicUrlAndTheToolSkills"]),
    "VER-SERVER-002": ("a2a-validate rule 1", ["ValidationTest#unsupportedVersionIsRejected", "DmnTest#validatesRequests"]),
    "VER-SERVER-003": ("a2a-validate: empty or missing A2A-Version is accepted", ["ValidationTest#patchVersionAndMissingVersionAreAccepted"]),
    "JSONRPC-FMT-001": ("a2a-rpc: Parse request, response builders", ["ValidationTest#unknownMethodAndInvalidRequest", "ValidationTest#idIsEchoedAndListTasksReturnsEmptyPage"]),
    "JSONRPC-FMT-002": ("a2a-rpc webhook response expression", ["WebhookIntegrationTest#sendMessageGetTaskAndCancelRoundTripThroughTheRealConnectors"]),
    "JSONRPC-SVC-001": ("a2a-validate: PascalCase method names", ["DmnTest#validatesRequests"]),
    "JSONRPC-SVC-002": ("a2a-rpc: Parse request reads A2A-Version and Content-Type headers", ["ValidationTest#unsupportedVersionIsRejected", "ValidationTest#wrongContentTypeIsRejected"]),
    "JSONRPC-ERR-001": ("a2a-rpc: error object has code, message and data only", ["ValidationTest#capabilityErrors"]),
    "JSONRPC-ERR-002": ("a2a-validate error codes", ["DmnTest#validatesRequests"]),
    "JSONRPC-ERR-003": ("ErrorInfo in the data array", ["ValidationTest#capabilityErrors", "ValidationTest#unsupportedVersionIsRejected"]),
    "JSONRPC-SSE-002": ("a2a-validate and a2a-rpc error codes", ["DmnTest#validatesRequests", "TaskTest#unknownTaskIsNotFoundForGetCancelAndFollowUp"]),
}
NA = {
    "capability-not-declared": [
        "CORE-STREAM-001",
        "CORE-STREAM-002",
        "CORE-STREAM-003",
        "STREAM-ORDER-001",
        "STREAM-ORDER-002",
        "STREAM-ORDER-003",
        "STREAM-ORDER-004",
        "STREAM-SUB-001",
        "STREAM-SUB-002",
        "STREAM-SUB-003",
        "STREAM-SUB-004",
        "JSONRPC-SSE-001",
        "CARD-EXT-001",
        "CARD-EXT-002",
        "CORE-CAP-004"],
    "other-binding": [
        "GRPC-SVC-001", "GRPC-SVC-002", "GRPC-SVC-003", "GRPC-META-001", "GRPC-ERR-001", "GRPC-ERR-002", "GRPC-ERR-003",
        "HTTP_JSON-URL-001", "HTTP_JSON-URL-002", "HTTP_JSON-SVC-001", "HTTP_JSON-SVC-002", "HTTP_JSON-QP-001",
        "HTTP_JSON-ERR-001", "HTTP_JSON-ERR-002", "HTTP_JSON-STATUS-001", "HTTP_JSON-SSE-001",
        "BIND-EQUIV-001", "BIND-EQUIV-002", "BIND-EQUIV-003", "BIND-EQUIV-004"],
    "client-side": ["VER-CLIENT-001", "VER-CLIENT-002"],
    "not-exercised": [
        "CARD-SIGN-001", "CARD-SIGN-002", "CARD-SIGN-003", "CARD-SIGN-004", "AUTH-TLS-001", "AUTH-SERVER-002",
        "AUTH-INTASK-001", "AUTH-INTASK-002", "AUTH-INTASK-003", "AUTH-INTASK-004", "AUTH-SCOPE-001", "AUTH-SCOPE-002",
        "AUTH-SCOPE-003", "VER-SERVER-001"],
}
NA_BY_ID = {i: r for r, ids in NA.items() for i in ids}


def must_ids():
    """Loads the MUST ids with the pinned TCK's own registry; re-executes under the TCK interpreter if needed."""
    try:
        from tck.requirements.registry import get_must_requirements  # noqa: PLC0415
        return [r.id for r in get_must_requirements()]
    except ImportError:
        pass
    tck = os.environ.get("TCK_DIR") or os.path.join(os.environ.get("TMPDIR", "/tmp"), "camunda-a2a-3-tck")
    py = os.path.join(tck, ".venv", "bin", "python")
    if not os.path.exists(py):
        sys.exit("TCK not prepared: run tck/run.sh --once first or set TCK_DIR (looked for %s)" % py)
    code = ("import sys; from tck.requirements.registry import get_must_requirements;"
            "print('\\n'.join(r.id for r in get_must_requirements()))")
    out = subprocess.run([py, "-I", "-c", code], capture_output=True, text=True, cwd=tck)
    if out.returncode != 0:
        sys.exit("could not load the TCK registry: " + out.stderr)
    return out.stdout.split()


def test_exists(ref):
    cls, _, method = ref.partition("#")
    path = os.path.join(TESTS, cls + ".java")
    return os.path.exists(path) and re.search(r"\b%s\s*\(" % re.escape(method), open(path).read()) is not None


def matrix(ids):
    rows = ["| Requirement | Element | Test | N/A reason |",
            "|-------------|---------|------|------------|"]
    for i in ids:
        if i in IMPLEMENTED:
            elements, tests = IMPLEMENTED[i]
            rows.append("| %s | %s | %s | |" % (i, elements, "; ".join("`%s`" % t for t in tests)))
        else:
            rows.append("| %s | | | %s |" % (i, NA_BY_ID.get(i, "")))
    return "\n".join(rows)


def readme_matrix():
    text = open(README).read()
    if BEGIN not in text or END not in text:
        return None, text
    return text.split(BEGIN)[1].split(END)[0], text


def verify(ids):
    body, _ = readme_matrix()
    problems = []
    if body is None:
        return ["README.md has no trace markers %s ... %s" % (BEGIN, END)]
    rows = {}
    for line in body.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) == 4 and re.match(r"^[A-Z][A-Z0-9_]*-", cells[0]):
            rows[cells[0]] = cells
    for i in ids:
        if i not in rows:
            problems.append("%s is missing from the README matrix" % i)
            continue
        _, _, tests, na = rows[i]
        refs = re.findall(r"`([A-Za-z]+#[A-Za-z0-9_]+)`", tests)
        if refs:
            for r in refs:
                if not test_exists(r):
                    problems.append("%s names test %s which does not exist" % (i, r))
        elif na not in NA_REASONS:
            problems.append("%s has neither a test nor an N/A reason from %s" % (i, NA_REASONS))
    for i in rows:
        if i not in ids:
            problems.append("README matrix lists %s which is not a MUST requirement of the pinned TCK" % i)
    return problems


def main(argv):
    ids = must_ids()
    if len(ids) < 100:
        sys.exit("expected about 114 MUST requirements, the registry returned %d" % len(ids))
    if "--update" in argv:
        body, text = readme_matrix()
        if body is None:
            sys.exit("README.md has no trace markers")
        head, rest = text.split(BEGIN)
        tail = rest.split(END)[1]
        open(README, "w").write(head + BEGIN + "\n" + matrix(ids) + "\n" + END + tail)
    problems = verify(ids)
    tested = sum(1 for i in ids if i in IMPLEMENTED)
    print("MUST requirements: %d, with tests: %d, N/A: %d, problems: %d" % (len(ids), tested, len(ids) - tested, len(problems)))
    for p in problems:
        print("  PROBLEM: " + p)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
