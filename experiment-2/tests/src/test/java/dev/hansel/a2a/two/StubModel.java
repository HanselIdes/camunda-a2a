package dev.hansel.a2a.two;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ArrayNode;
import com.fasterxml.jackson.databind.node.ObjectNode;
import com.sun.net.httpserver.HttpServer;
import java.net.InetSocketAddress;
import java.util.List;
import java.util.concurrent.CopyOnWriteArrayList;
import java.util.function.Function;

/**
 * An OpenAI-compatible chat completions endpoint in the test JVM. The AI Agent connector asks for a stream, so it
 * answers with server-sent chunks. What the model does next is up to the test's decide function.
 */
final class StubModel {
  static final ObjectMapper JSON = new ObjectMapper();

  /** The model's next step: one tool call, or a plain reply. */
  record Step(String toolName, String arguments, String content) {
    static Step call(final String toolName, final String arguments) {
      return new Step(toolName, arguments, null);
    }

    static Step reply(final String content) {
      return new Step(null, null, content);
    }
  }

  final List<JsonNode> requests = new CopyOnWriteArrayList<>();
  final HttpServer server;

  StubModel(final Function<JsonNode, Step> decide) {
    try {
      server = HttpServer.create(new InetSocketAddress("0.0.0.0", 0), 0);
    } catch (final Exception e) {
      throw new IllegalStateException(e);
    }
    server.createContext("/v1/chat/completions", exchange -> {
      final var request = JSON.readTree(exchange.getRequestBody().readAllBytes());
      requests.add(request);
      final byte[] body = stream(decide.apply(request)).getBytes();
      exchange.getResponseHeaders().add("Content-Type", "text/event-stream");
      exchange.sendResponseHeaders(200, body.length);
      exchange.getResponseBody().write(body);
      exchange.close();
    });
    server.start();
  }

  String baseUrlFromConnectors() {
    return "http://host.docker.internal:" + server.getAddress().getPort() + "/v1";
  }

  static String systemPrompt(final JsonNode request) {
    for (final JsonNode m : request.get("messages")) {
      if ("system".equals(m.path("role").asText())) {
        return text(m.get("content"));
      }
    }
    return "";
  }

  static String lastUser(final JsonNode request) {
    String user = "";
    for (final JsonNode m : request.get("messages")) {
      if ("user".equals(m.path("role").asText())) {
        user = text(m.get("content"));
      }
    }
    return user;
  }

  /** The content of the last message when it is a tool result, else null. */
  static String lastToolResult(final JsonNode request) {
    final JsonNode messages = request.get("messages");
    final JsonNode last = messages.get(messages.size() - 1);
    return "tool".equals(last.path("role").asText()) ? text(last.get("content")) : null;
  }

  static List<String> toolNames(final JsonNode request) {
    final var names = new java.util.ArrayList<String>();
    request.path("tools").forEach(t -> names.add(t.path("function").path("name").asText()));
    return names;
  }

  static String stream(final Step step) {
    try {
      final String id = "stub-" + System.nanoTime();
      final ObjectNode delta = JSON.createObjectNode().put("role", "assistant");
      if (step.toolName() != null) {
        final ArrayNode calls = JSON.createArrayNode();
        final var call = calls.addObject().put("index", 0).put("id", "call_" + System.nanoTime()).put("type", "function");
        call.putObject("function").put("name", step.toolName()).put("arguments", step.arguments());
        delta.set("tool_calls", calls);
      } else {
        delta.put("content", step.content());
      }
      final var sb = new StringBuilder();
      sb.append(chunk(id, delta, null))
          .append(chunk(id, JSON.createObjectNode(), step.toolName() != null ? "tool_calls" : "stop"));
      final var usage = JSON.createObjectNode().put("id", id).put("object", "chat.completion.chunk").put("created", 1L)
          .put("model", "stub");
      usage.putArray("choices");
      usage.putObject("usage").put("prompt_tokens", 1).put("completion_tokens", 1).put("total_tokens", 2);
      sb.append("data: ").append(JSON.writeValueAsString(usage)).append("\n\n").append("data: [DONE]\n\n");
      return sb.toString();
    } catch (final Exception e) {
      throw new IllegalStateException(e);
    }
  }

  static String chunk(final String id, final JsonNode delta, final String finish) throws Exception {
    final var out = JSON.createObjectNode().put("id", id).put("object", "chat.completion.chunk").put("created", 1L)
        .put("model", "stub");
    final var choice = out.putArray("choices").addObject().put("index", 0);
    choice.set("delta", delta);
    if (finish == null) {
      choice.putNull("finish_reason");
    } else {
      choice.put("finish_reason", finish);
    }
    return "data: " + JSON.writeValueAsString(out) + "\n\n";
  }

  static String text(final JsonNode content) {
    if (content == null || content.isNull()) {
      return "";
    }
    if (content.isTextual()) {
      return content.asText();
    }
    final var sb = new StringBuilder();
    content.forEach(part -> sb.append(part.path("text").asText()));
    return sb.toString();
  }
}
