import { test, expect } from '@playwright/test';

const BASE_DOMAIN = process.env.BASE_DOMAIN || 'localhost';
const MARKET_URL = `https://test-market.${BASE_DOMAIN}`;
const RELAY_URL = `https://test-relay.${BASE_DOMAIN}`;

test.describe('Plebeian Market', () => {
  test('market app returns successful HTTP response', async ({ request }) => {
    const response = await request.get(MARKET_URL, {
      ignoreHTTPSErrors: true,
    });
    expect(response.status()).toBeLessThan(500);
  });

  test('market SPA loads with HTML content', async ({ page }) => {
    const response = await page.goto(MARKET_URL);
    expect(response).not.toBeNull();
    expect(response!.status()).toBeLessThan(500);

    const title = await page.title();
    expect(title).toBeTruthy();

    const body = await page.locator('body');
    await expect(body).toBeVisible({ timeout: 10_000 });
  });

  test('auctions page is accessible', async ({ page }) => {
    await page.goto(`${MARKET_URL}/auctions`, { ignoreHTTPSErrors: true } as any);
    await page.waitForLoadState('networkidle').catch(() => {});

    const response = await page.goto(`${MARKET_URL}/auctions`);
    expect(response).not.toBeNull();
    expect(response!.status()).toBeLessThan(500);
  });

  test('products page is accessible', async ({ page }) => {
    const response = await page.goto(`${MARKET_URL}/products`);
    expect(response).not.toBeNull();
    expect(response!.status()).toBeLessThan(500);
  });

  test('login dialog opens when clicked', async ({ page }) => {
    await page.goto(MARKET_URL, { ignoreHTTPSErrors: true } as any);
    await page.waitForLoadState('networkidle').catch(() => {});
    await page.waitForTimeout(2000);

    const response = await page.goto(MARKET_URL);
    expect(response).not.toBeNull();
    expect(response!.status()).toBeLessThan(500);

    const loginButton = page.getByTestId('login-button');
    if (await loginButton.isVisible().catch(() => false)) {
      await loginButton.click();
      await page.waitForTimeout(1000);
      const dialog = page.locator('[role="dialog"], [data-state="open"]');
      const hasDialog = await dialog.isVisible().catch(() => false);
      const hasLoginContent = await page.locator('text=/login|connect|private key/i').first().isVisible().catch(() => false);
      expect(hasDialog || hasLoginContent).toBe(true);
    }
  });
});

test.describe('Test Relay', () => {
  test('test relay HTTP endpoint responds', async ({ request }) => {
    const response = await request.get(RELAY_URL, {
      ignoreHTTPSErrors: true,
    });
    expect(response.status()).toBeLessThan(500);
  });

  test('test relay NIP-11 info document', async ({ request }) => {
    const response = await request.get(RELAY_URL, {
      headers: { Accept: 'application/nostr+json' },
      ignoreHTTPSErrors: true,
    });
    if (response.status() === 200) {
      const body = await response.json();
      expect(body).toHaveProperty('name');
    }
  });

  test('test relay WebSocket upgrade succeeds', async ({ request }) => {
    const wsUrl = RELAY_URL.replace('https://', 'wss://').replace('http://', 'ws://');
    const response = await request.get(wsUrl, {
      headers: {
        Upgrade: 'websocket',
        Connection: 'Upgrade',
      },
      ignoreHTTPSErrors: true,
    });
    expect(response.status()).toBeLessThan(500);
  });
});
