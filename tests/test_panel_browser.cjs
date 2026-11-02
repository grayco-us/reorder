/* Optional browser smoke test. Uses only local fixture files and mocked HA calls. */
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');
const { chromium } = require('playwright');
(async () => {
  const root = path.resolve(__dirname, '..');
  const artifacts = process.env.REORDER_ARTIFACT_DIR || path.join(require('node:os').tmpdir(), 'reorder-panel-artifacts');
  await fs.mkdir(artifacts, { recursive: true });
  const browser = await chromium.launch({ headless: true, executablePath: process.env.REORDER_CHROMIUM_PATH, args: ['--no-sandbox'] });
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    const allowed = new Set(['/tests/panel_fixture.html', '/tests/panel-fixture.mjs', '/custom_components/reorder/www/reorder-panel.js']);
    await page.route('**/*', async route => {
      const url = new URL(route.request().url());
      if (url.hostname !== 'reorder.test' || !allowed.has(url.pathname)) return route.abort();
      return route.fulfill({ body: await fs.readFile(path.join(root, url.pathname)), contentType: url.pathname.endsWith('.html') ? 'text/html' : 'text/javascript' });
    });
    await page.goto('http://reorder.test/tests/panel_fixture.html');
    await page.getByRole('button', { name: /Ready for review/ }).click();
    await page.getByRole('link', { name: /Cat litter/ }).waitFor();
    assert.equal(await page.getByRole('button', { name: 'Cancel locally', exact: true }).isDisabled(), false);
    assert.equal(await page.getByRole('button', { name: 'Refresh status', exact: true }).isDisabled(), true);
    assert.equal(await page.evaluate(() => window.reorderCalls.filter(call => call.type === 'call_service').length), 0);
    await page.screenshot({ path: path.join(artifacts, 'reorder-sidebar-desktop.png'), fullPage: true });
    await page.setViewportSize({ width: 390, height: 1100 });
    await page.screenshot({ path: path.join(artifacts, 'reorder-sidebar-mobile.png'), fullPage: true });
    assert.equal(await page.evaluate(() => document.querySelector('reorder-panel').shadowRoot.querySelector('main').scrollWidth <= 390), true);
    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.getByRole('button', { name: /Order placed/ }).click();
    assert.equal(await page.getByRole('button', { name: 'Cancel locally', exact: true }).isDisabled(), true);
    await page.getByRole('button', { name: 'Refresh status', exact: true }).click();
    await page.getByRole('status').filter({ hasText: 'Status refreshed from Zinc.' }).waitFor();
    await page.getByRole('button', { name: /Needs reconciliation/ }).click();
    assert.equal(await page.getByRole('button', { name: 'Cancel locally', exact: true }).isDisabled(), true);
    assert.equal(await page.getByRole('button', { name: 'Refresh status', exact: true }).isDisabled(), true);
    await page.getByText('The submission outcome is uncertain.', { exact: false }).waitFor();
    await page.getByRole('button', { name: /Ready for review/ }).click();
    await page.getByRole('button', { name: 'Cancel locally', exact: true }).click();
    await page.getByRole('button', { name: 'Keep batch', exact: true }).click();
    assert.equal(await page.evaluate(() => window.reorderCalls.filter(call => call.service === 'cancel_batch').length), 0);
    await page.getByRole('button', { name: 'Cancel locally', exact: true }).click();
    await page.getByRole('button', { name: 'Confirm local cancellation', exact: true }).click();
    await page.getByRole('heading', { name: 'Canceled', exact: true }).waitFor();
    assert.equal(await page.evaluate(() => window.reorderCalls.filter(call => call.service === 'cancel_batch').length), 1);
    await page.getByRole('button', { name: /^Queue/ }).click();
    await page.getByRole('link', { name: /Morning coffee/ }).waitFor();
    await page.getByRole('button', { name: 'Prepare batch for review', exact: true }).click();
    await page.getByText('Batch prepared locally. No purchase was made.', { exact: true }).waitFor();
    await page.getByRole('button', { name: /Order placed/ }).click();
    await page.evaluate(() => { window.failNextAction = true; });
    await page.getByRole('button', { name: 'Refresh status', exact: true }).click();
    await page.getByRole('alert').filter({ hasText: 'Simulated network failure' }).waitFor();
    await page.evaluate(() => {
      window.snapshot.batches.find(batch => batch.id === 'placed-batch').orders[0].name = '<img src=x onerror="window.hacked=true">';
      window.pushSnapshot();
    });
    await page.getByRole('link', { name: '<img src=x onerror="window.hacked=true">', exact: false }).waitFor();
    assert.equal(await page.locator('reorder-panel img').count(), 0);
    assert.equal(await page.evaluate(() => window.hacked), undefined);
    assert.equal(await page.evaluate(() => window.reorderCalls.some(call => String(call.service).includes('submit'))), false);
    assert.deepEqual(errors, []);
    console.log('PASS: desktop/mobile rendering, inline review, button eligibility, refresh, explicit local cancellation, queue preparation, errors, and escaped product text; no purchase calls.');
    console.log('Screenshots: ' + artifacts + '/reorder-sidebar-{desktop,mobile}.png');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
