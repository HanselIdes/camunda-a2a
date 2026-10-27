import { layoutProcess } from 'bpmn-auto-layout';

let xml = '';
for await (const chunk of process.stdin) {
  xml += chunk;
}

try {
  const result = await layoutProcess(xml);
  const output = typeof result === 'string' ? result : result.xml;
  const warnings = typeof result === 'string' ? [] : result.warnings || [];
  if (warnings.length) {
    process.stderr.write(JSON.stringify(warnings.map((warning) => ({
      message: warning.message,
      elementId: warning.element && warning.element.id
    }))));
  }
  process.stdout.write(output);
} catch (error) {
  process.stderr.write(error.stack || String(error));
  process.exitCode = 1;
}
