#!/usr/bin/env node
const path = require('node:path');
const { createRequire } = require('node:module');

const url = process.env.CI_DASHBOARD_URL || 'https://ci.orangesync.tech/';
const expectedTitle = process.env.CI_DASHBOARD_TITLE || 'ngit-ci · Nostr CI Dashboard';

function loadPlaywright() {
  try {
    return require('playwright');
  } catch (err) {
    const home = process.env.PLAYWRIGHT_HOME;
    if (!home) {
      throw new Error(
        'cannot resolve playwright — set PLAYWRIGHT_HOME to a directory containing node_modules/playwright',
      );
    }
    return createRequire(path.join(home, 'package.json'))('playwright');
  }
}

async function main() {
  const { chromium } = loadPlaywright();
  const browser = await chromium.launch({ channel: 'chrome' });
  const page = await browser.newPage();
  const consoleErrors = [];
  const pageErrors = [];
  page.on('console', (msg) => {
    if (msg.type() === 'error') consoleErrors.push(msg.text());
  });
  page.on('pageerror', (err) => pageErrors.push(err.message));

  const response = await page.goto(url, { waitUntil: 'load', timeout: 30000 });
  const status = response ? response.status() : 0;
  await page.waitForSelector('.run-list', { timeout: 20000 });
  await page.waitForTimeout(3000);

  const title = await page.title();
  const runRows = await page.locator('.run-row').count();
  const emptyStates = await page.locator('.empty-state').count();
  const liveDotPresent = (await page.locator('.live-dot').count()) > 0;
  const relayConnected = (await page.locator('.live-dot.live').count()) > 0;
  const headerText = await page.locator('.dash-header').innerText().catch(() => '');
  const appText = await page.locator('#app').innerText().catch(() => '');

  await browser.close();

  const report = {
    url,
    status,
    title,
    expectedTitle,
    titleOk: title === expectedTitle,
    runListPresent: true,
    runRows,
    emptyStates,
    liveDotPresent,
    relayConnected,
    headerText: headerText.replace(/\s+/g, ' ').trim(),
    appTextHead: appText.replace(/\s+/g, ' ').trim().slice(0, 200),
    pageErrors,
    consoleErrors,
  };
  console.log(JSON.stringify(report, null, 2));

  const failures = [];
  if (status !== 200) failures.push(`http status ${status}`);
  if (title !== expectedTitle) failures.push(`title mismatch: ${JSON.stringify(title)}`);
  if (pageErrors.length) failures.push(`${pageErrors.length} uncaught page error(s)`);
  if (failures.length) {
    console.error(`FAIL: ${failures.join('; ')}`);
    process.exit(1);
  }
  console.log(`PASS: title + .run-list present, ${runRows} run row(s), no uncaught errors`);
}

main().catch((err) => {
  console.error(`FAIL: ${err.message}`);
  process.exit(1);
});
