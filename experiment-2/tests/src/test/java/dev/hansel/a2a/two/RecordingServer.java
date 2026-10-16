package dev.hansel.a2a.two;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.sun.net.httpserver.HttpServer;
import java.net.InetSocketAddress;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.CopyOnWriteArrayList;
import java.util.function.Function;

/**
 * An HTTP server in the test JVM that records every request and answers with whatever the test registered for
 * the path. The connectors container reaches it at host.docker.internal.
 */
final class RecordingServer {
  static final ObjectMapper JSON = new ObjectMapper();

  record Request(String method, String path, String query, Map<String, List<String>> headers, String body) {
    JsonNode json() {
      try {
        return JSON.readTree(body);
      } catch (final Exception e) {
        throw new IllegalStateException("not JSON: " + body, e);
      }
    }

    String header(final String name) {
      return headers.entrySet().stream().filter(e -> e.getKey().equalsIgnoreCase(name)).findFirst()
          .map(e -> e.getValue().get(0)).orElse(null);
    }
  }

  record Response(int status, String body) {}

  final List<Request> requests = new CopyOnWriteArrayList<>();
  final Map<String, Function<Request, Response>> routes = new ConcurrentHashMap<>();
  final HttpServer server;

  RecordingServer() {
    try {
      server = HttpServer.create(new InetSocketAddress("0.0.0.0", 0), 0);
    } catch (final Exception e) {
      throw new IllegalStateException(e);
    }
    server.createContext("/", exchange -> {
      final var request = new Request(exchange.getRequestMethod(), exchange.getRequestURI().getPath(),
          exchange.getRequestURI().getRawQuery(), Map.copyOf(exchange.getRequestHeaders()),
          new String(exchange.getRequestBody().readAllBytes()));
      requests.add(request);
      final var route = routes.getOrDefault(request.path(), r -> new Response(200, "{}"));
      final var response = route.apply(request);
      final byte[] body = response.body().getBytes();
      exchange.getResponseHeaders().add("Content-Type", "application/json");
      exchange.sendResponseHeaders(response.status(), body.length);
      exchange.getResponseBody().write(body);
      exchange.close();
    });
    server.start();
  }

  /** The base URL as the connectors container sees it. */
  String urlFromConnectors() {
    return "http://host.docker.internal:" + server.getAddress().getPort();
  }

  List<Request> requestsTo(final String path) {
    return requests.stream().filter(r -> r.path().equals(path)).toList();
  }
}
