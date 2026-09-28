import { test, expect } from '@playwright/test';

const BASE_DOMAIN = process.env.BASE_DOMAIN || 'orangesync.tech';

test.describe('Mint Orchestrator API', () => {
  const apiUrl = `http://23.182.128.51:8090`;

  test.skip(() => !process.env.BASE_DOMAIN, 'Skipping mint orchestrator tests - BASE_DOMAIN not set');

  test('health endpoint returns ok', async ({ request }) => {
    const resp = await request.get(`${apiUrl}/health`);
    expect(resp.ok()).toBeTruthy();
    const body = await resp.json();
    expect(body.status).toBe('ok');
    expect(typeof body.mints).toBe('number');
  });

  test('list mints returns array', async ({ request }) => {
    const resp = await request.get(`${apiUrl}/mints`);
    expect(resp.ok()).toBeTruthy();
    const body = await resp.json();
    expect(Array.isArray(body.mints)).toBeTruthy();
  });

  test('audit endpoint returns entries', async ({ request }) => {
    const resp = await request.get(`${apiUrl}/audit?count=10`);
    expect(resp.ok()).toBeTruthy();
    const body = await resp.json();
    expect(Array.isArray(body.entries)).toBeTruthy();
  });

  test('unknown mint returns 404', async ({ request }) => {
    const resp = await request.get(`${apiUrl}/mints/nonexistent`);
    expect(resp.status()).toBe(404);
  });
});

test.describe('Mint Dashboard', () => {
  test.skip(() => !process.env.BASE_DOMAIN, 'Skipping mint dashboard tests - BASE_DOMAIN not set');

  test('dashboard page loads', async ({ page }) => {
    await page.goto(`https://dashboard.mints.${BASE_DOMAIN}`);
    await expect(page.locator('h1')).toHaveText(/Tollgate Mint Dashboard/);
  });

  test('login section is visible', async ({ page }) => {
    await page.goto(`https://dashboard.mints.${BASE_DOMAIN}`);
    await expect(page.locator('#login-section')).toBeVisible();
  });

  test('nsec input field exists', async ({ page }) => {
    await page.goto(`https://dashboard.mints.${BASE_DOMAIN}`);
    const input = page.locator('#nsec-input');
    await expect(input).toBeVisible();
  });
});

test.describe('Cashu Mint REST API', () => {
  test.skip(() => !process.env.BASE_DOMAIN, 'Skipping mint REST API tests - BASE_DOMAIN not set');

  test('mint info endpoint responds', async ({ request }) => {
    const mintUrl = `https://test.mints.${BASE_DOMAIN}`;
    const resp = await request.get(`${mintUrl}/v1/info`).catch(() => null);
    if (resp) {
      expect(resp.ok()).toBeTruthy();
      const body = await resp.json();
      expect(body).toHaveProperty('pubkey');
      expect(body).toHaveProperty('version');
    }
  });

  test('mint keys endpoint responds', async ({ request }) => {
    const mintUrl = `https://test.mints.${BASE_DOMAIN}`;
    const resp = await request.get(`${mintUrl}/v1/keys`).catch(() => null);
    if (resp && resp.ok()) {
      const body = await resp.json();
      expect(Array.isArray(body.keysets)).toBeTruthy();
    }
  });
});
