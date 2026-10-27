#!/usr/bin/env node
const fs = require('node:fs');
const Ajv = require('ajv');
const addErrors = require('ajv-errors');
const schema = require('@bpmn-io/form-json-schema/resources/schema.json');
const ajv = new Ajv({ allErrors: true, strict: false });
addErrors(ajv);
const validate = ajv.compile(schema);
const files = process.argv.slice(2);
if (!files.length) {
  throw new Error('Usage: node tools/validate_forms.cjs FILE.form [...]');
}
for (const file of files) {
  const form = JSON.parse(fs.readFileSync(file, 'utf8'));
  if (!validate(form)) {
    throw new Error(`${file}: ${JSON.stringify(validate.errors)}`);
  }
  const ids = new Set();
  const keys = new Set();
  function check(components) {
    for (const component of components) {
      if (ids.has(component.id)) throw new Error(`${file}: duplicate component id ${component.id}`);
      ids.add(component.id);
      if ('value' in component || component.type === 'submit' ||
          (component.type === 'button' && 'key' in component)) {
        throw new Error(`${file}: invalid component shape ${component.id}`);
      }
      if (component.key) {
        if (keys.has(component.key)) throw new Error(`${file}: duplicate field key ${component.key}`);
        keys.add(component.key);
      }
      if (component.components) check(component.components);
    }
  }
  check(form.components);
  console.log(`${file}: schema and field shapes PASS`);
}
