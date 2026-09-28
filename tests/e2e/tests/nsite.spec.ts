import { test, expect } from '@playwright/test';

const BASE_DOMAIN = process.env.BASE_DOMAIN || 'localhost';

test.describe('NSite Gateway', () => {
  test('nsite gateway is accessible', async ({ page }) => {
    const response = await page.goto(`https://nsite.${BASE_DOMAIN}/`, {
      waitUntil: 'networkidle',
      timeout: 15000,
    });
    expect(response).not.toBeNull();
    expect(response!.status()).toBeLessThan(500);
  });
});
