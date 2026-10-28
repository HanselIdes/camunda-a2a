"""Migrate inherited blueprint settings without rewriting archived generators."""
import re


REFERENCE = re.compile(r"\{\{secrets\.([A-Za-z_][A-Za-z0-9_]*)\}\}")


def current_secret_expression(value):
    if not isinstance(value, str) or not REFERENCE.search(value):
        return value
    whole = REFERENCE.fullmatch(value)
    if whole:
        return "=camunda.secrets." + whole[1]
    if not value.startswith("="):
        raise ValueError("Embedded secret requires an explicit FEEL expression")
    migrated = re.sub(r'"\{\{secrets\.([A-Za-z_][A-Za-z0-9_]*)\}\}"',
                      r"camunda.secrets.\1", value)
    if REFERENCE.search(migrated):
        raise ValueError("Secret inside a string literal requires explicit FEEL composition")
    return migrated


def current_secret_mappings(root):
    for node in root.iter():
        for key, value in node.attrib.items():
            node.set(key, current_secret_expression(value))
    return root
