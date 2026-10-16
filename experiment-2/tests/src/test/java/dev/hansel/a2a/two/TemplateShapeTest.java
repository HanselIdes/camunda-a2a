package dev.hansel.a2a.two;

import static org.assertj.core.api.Assertions.assertThat;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.stream.Stream;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.MethodSource;

/** What every A2A 1.0 template shows in Modeler, read from the generated JSON. */
class TemplateShapeTest {
  static final ObjectMapper JSON = new ObjectMapper();
  /** An HTML-like tag other than a link: Modeler renders descriptions as HTML and drops such text. */
  static final String PLACEHOLDER_TAG = "<(?!/?a[ >])[A-Za-z][^>]*>";

  static Stream<Path> templates() throws Exception {
    return Files.list(Path.of("../element-templates")).filter(p -> p.toString().endsWith(".json")).sorted();
  }

  static JsonNode property(final JsonNode template, final String bindingName) {
    for (final JsonNode p : template.path("properties")) {
      if (bindingName.equals(p.path("binding").path("name").asText())
          || bindingName.equals(p.path("binding").path("key").asText())) {
        return p;
      }
    }
    return null;
  }

  @ParameterizedTest
  @MethodSource("templates")
  void everyTemplateShowsAResultVariableAndAResultExpression(final Path file) throws Exception {
    final JsonNode template = JSON.readTree(file.toFile());
    for (final String name : new String[] {"resultVariable", "resultExpression"}) {
      final JsonNode p = property(template, name);
      assertThat(p).as(file.getFileName() + " " + name).isNotNull();
      assertThat(p.path("type").asText()).as(file.getFileName() + " " + name + " is visible").isNotEqualTo("Hidden");
    }
  }

  @ParameterizedTest
  @MethodSource("templates")
  void noDescriptionUsesAngleBracketsThatModelerWouldHide(final Path file) throws Exception {
    final JsonNode template = JSON.readTree(file.toFile());
    assertThat(template.path("description").asText()).doesNotContainPattern(PLACEHOLDER_TAG);
    for (final JsonNode p : template.path("properties")) {
      assertThat(p.path("description").asText()).as(file.getFileName() + " " + p.path("id").asText())
          .doesNotContainPattern(PLACEHOLDER_TAG);
    }
  }
}
