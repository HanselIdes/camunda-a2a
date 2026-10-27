const Ajv = require('ajv');
const addErrors = require('ajv-errors');
const fs = require('fs');
const schema = require('@bpmn-io/form-json-schema/resources/schema.json');
const file = process.argv[2];

if (!file) {
  console.error('Usage: node validate-form.cjs <path-to-form.form>');
  process.exit(1);
}

let form;
try {
  form = JSON.parse(fs.readFileSync(file, 'utf8'));
} catch (error) {
  console.error(`Cannot read/parse ${file}: ${error.message}`);
  process.exit(1);
}

const ajv = new Ajv({ allErrors: true, strict: false });
addErrors(ajv);
const validate = ajv.compile(schema);
if (!validate(form)) {
  console.error(JSON.stringify(validate.errors, null, 2));
  process.exit(1);
}

function invalidComponentShapes(components, path = 'components') {
  if (!Array.isArray(components)) return [];
  const errors = [];
  for (const [index, component] of components.entries()) {
    if (!component || typeof component !== 'object' || Array.isArray(component)) continue;
    const location = `${path}[${index}]`;
    if (Object.prototype.hasOwnProperty.call(component, 'value')) {
      errors.push(`${location}: use defaultValue instead of value on a component`);
    }
    if (component.type === 'submit') {
      errors.push(`${location}: use type "button" with action "submit"`);
    }
    if (component.type === 'button' && Object.prototype.hasOwnProperty.call(component, 'key')) {
      errors.push(`${location}: buttons must not define key`);
    }
    errors.push(...invalidComponentShapes(component.components, `${location}.components`));
  }
  return errors;
}

const shapeErrors = invalidComponentShapes(form.components);
if (shapeErrors.length) {
  console.error(JSON.stringify(shapeErrors, null, 2));
  process.exit(1);
}

console.log(`Valid: ${file}`);
