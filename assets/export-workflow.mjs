// Export the checked Archify viewer through its own canonical SVG exporter.
// Run from the repository root with the path to a pinned Archify checkout.
import fs from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

if (process.argv.length !== 3) {
  throw new Error('Usage: node assets/export-workflow.mjs <archify-checkout>');
}
const driver = path.resolve(process.argv[2], 'archify/bin/visual-check.mjs');
const { ChromeVisualBrowser, findChrome } = await import(pathToFileURL(driver).href);
const chrome = findChrome();
if (!chrome) throw new Error('Chrome or Chromium is required for SVG export.');
const browser = new ChromeVisualBrowser(chrome);
try {
  const session = await browser.sessionPromise;
  const send = (method, params = {}) => browser.cdp.send(method, params, session);
  const evaluate = async expression => {
    const result = await send('Runtime.evaluate', {
      expression, awaitPromise: true, returnByValue: true,
    });
    if (result.exceptionDetails) {
      throw new Error(result.exceptionDetails.exception?.description
        || JSON.stringify(result.exceptionDetails));
    }
    return result.result?.value;
  };
  await send('Emulation.setDeviceMetricsOverride', {
    width: 1440, height: 900, deviceScaleFactor: 1, mobile: false,
  });
  const loaded = browser.cdp.waitFor('Page.loadEventFired', session);
  await send('Page.navigate', {
    url: pathToFileURL(path.resolve('assets/workflow.html')).href,
  });
  await loaded;
  await evaluate('document.fonts.ready');
  await evaluate('Archify.readerLayout.whenStable()');

  // Capture the download boundary; Archify still serializes the actual SVG.
  await evaluate(`
    window.exportBlobs = new Map();
    window.lastExport = null;
    const create = URL.createObjectURL.bind(URL);
    URL.createObjectURL = blob => {
      const url = create(blob);
      exportBlobs.set(url, blob);
      return url;
    };
    const click = HTMLAnchorElement.prototype.click;
    HTMLAnchorElement.prototype.click = function () {
      if (this.download) {
        window.lastExport = exportBlobs.get(this.href);
        return;
      }
      return click.call(this);
    };
  `);
  for (const theme of ['light', 'dark']) {
    const svg = await evaluate(`(async () => {
      window.lastExport = null;
      await Archify.exportMenu.run('svg-${theme}');
      if (!lastExport) throw new Error('No SVG exported');
      return await lastExport.text();
    })()`);
    const output = `assets/workflow-${theme}.svg`;
    fs.writeFileSync(output, svg);
    console.log(output);
  }
} finally {
  await browser.close();
}
