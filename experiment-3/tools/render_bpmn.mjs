import { createServer } from 'node:http';
import { readFile, mkdir, writeFile } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import { chromium } from 'playwright';

const paths = process.argv.slice(2).map((path) => resolve(path));
if (!paths.length) {
  throw new Error('Usage: node tools/render_bpmn.mjs <diagram.bpmn> [...]');
}

const modelerScript = resolve('node_modules/bpmn-js/dist/bpmn-modeler.production.min.js');
const server = createServer(async (request, response) => {
  if (request.url === '/modeler.js') {
    response.writeHead(200, { 'content-type': 'text/javascript' });
    response.end(await readFile(modelerScript));
    return;
  }
  response.writeHead(200, { 'content-type': 'text/html' });
  response.end(`<!doctype html><html><head><meta charset="utf-8"><style>
    html,body,#canvas{margin:0;width:2400px;height:1600px;overflow:hidden}
    .bjs-powered-by,.djs-palette,.djs-context-pad,.bjs-breadcrumbs{display:none!important}
    </style></head><body><div id="canvas"></div><script src="/modeler.js"></script></body></html>`);
});
await new Promise((resolveListen) => server.listen(0, '127.0.0.1', resolveListen));

const browser = await chromium.launch({ headless: true });
try {
  const page = await browser.newPage({ viewport: { width: 2400, height: 1600 }, deviceScaleFactor: 1 });
  await page.goto(`http://127.0.0.1:${server.address().port}`);
  for (const path of paths) {
    const xml = await readFile(path, 'utf8');
    const rendered = await page.evaluate(async (source) => {
      window.modeler = new window.BpmnJS({ container: '#canvas', keyboard: { bindTo: null } });
      await window.modeler.importXML(source);
      window.modeler.get('canvas').zoom('fit-viewport');
      const { svg } = await window.modeler.saveSVG();
      const elements = window.modeler.get('elementRegistry').getAll()
        .filter((element) => element.type !== 'label' && element.x !== undefined)
        .map((element) => ({ id: element.id, type: element.type, x: element.x, y: element.y,
          width: element.width, height: element.height }));
      return { svg, elements };
    }, xml);
    const output = path.replaceAll('\\', '/').replace(/^.*?experiment-3\//, '');
    const safeName = output.replaceAll('/', '__').replace(/\.bpmn$/, '');
    const outputDir = resolve(process.env.BPMN_RENDER_DIR || 'bpmn-render');
    const svgPath = resolve(outputDir, `${safeName}.svg`);
    const pngPath = resolve(outputDir, `${safeName}.png`);
    await mkdir(dirname(svgPath), { recursive: true });
    await writeFile(svgPath, rendered.svg);
    await page.screenshot({ path: pngPath, clip: { x: 0, y: 0, width: 2400, height: 1600 } });
    await writeFile(resolve(outputDir, `${safeName}.elements.json`),
      JSON.stringify(rendered.elements, null, 2) + '\n');
    await page.evaluate(() => window.modeler.destroy());
    console.log(`${path} -> ${pngPath}`);
  }
} finally {
  await browser.close();
  await new Promise((resolveClose, rejectClose) => server.close((error) => error ? rejectClose(error) : resolveClose()));
}
