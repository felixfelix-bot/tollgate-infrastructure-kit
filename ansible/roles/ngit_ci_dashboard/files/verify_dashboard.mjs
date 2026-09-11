/**
 * Render-check the deployed ngit-ci dashboard.
 *
 * HTTP 200 is NOT acceptance: a static SPA can answer 200 while shipping a
 * broken bundle. This script loads the real URL in Chrome, waits for the first
 * render pass and reports what the page actually contains.
 *
 * usage: node verify_dashboard.mjs <url> <report.json> [wait_ms]
 *
 * Exit codes: 0 = report written, 2 = the page could not be driven at all.
 * The caller decides what to enforce (shell rendered / run rows present) by
 * reading the JSON report, so a healthy-but-empty run list is reported rather
 * than silently treated as success.
 */
import { writeFileSync } from 'node:fs';

const url = process.argv[2];
const reportPath = process.argv[3] ?? 'verify-report.json';
const waitMs = Number(process.argv[4] ?? 20000);

if (!url) {
  console.error('usage: node verify_dashboard.mjs <url> [report.json] [wait_ms]');
  process.exit(2);
}

let chromium;
try {
  ({ chromium } = await import('playwright'));
} catch {
  ({ chromium } = await import('@playwright/test'));
}

const report = {
  url,
  startedAt: new Date().toISOString(),
  httpStatus: null,
  title: null,
  headerText: null,
  shellRendered: false,
  runRows: 0,
  jobPaneText: null,
  runRowTexts: [],
  errors: [],
};

let browser;
try {
  browser = await chromium.launch({
    channel: 'chrome',
    args: ['--no-sandbox', '--disable-dev-shm-usage'],
  });
  const page = await browser.newPage({ colorScheme: 'dark', viewport: { width: 1280, height: 900 } });

  const response = await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 45_000 });
  report.httpStatus = response ? response.status() : null;
  report.title = await page.title();

  // Let the relay subscription settle and the first render pass run.
  await page.waitForTimeout(2_000);
  try {
    await page.waitForSelector('[data-testid=run-row]', { timeout: waitMs });
  } catch {
    // No runs published yet — counted below.
  }

  report.runRows = await page.locator('[data-testid=run-row]').count();
  report.runRowTexts = (await page.locator('[data-testid=run-row]').allInnerTexts())
    .map((t) => t.replace(/\s+/g, ' ').trim())
    .slice(0, 10);

  const headerCount = await page.locator('header.app-header h1').count();
  report.headerText = headerCount
    ? (await page.locator('header.app-header h1').first().innerText()).replace(/\s+/g, ' ').trim()
    : null;
  const paneCount = await page.locator('#job-pane').count();
  report.jobPaneText = paneCount ? (await page.locator('#job-pane').first().innerText()).trim() : null;

  const appChildren = await page.locator('#app > *').count();
  report.shellRendered =
    headerCount > 0 && appChildren >= 3 && (report.title ?? '').includes('ngit-ci');
} catch (error) {
  report.errors.push(String(error?.message ?? error));
} finally {
  if (browser) await browser.close();
  report.finishedAt = new Date().toISOString();
  writeFileSync(reportPath, `${JSON.stringify(report, null, 2)}\n`);
  console.log(JSON.stringify(report));
}

process.exit(report.errors.length > 0 ? 2 : 0);
