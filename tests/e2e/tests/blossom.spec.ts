import { test, expect } from '@playwright/test';

const BASE_DOMAIN = process.env.BASE_DOMAIN || 'localhost';

test.describe('Blossom Server', () => {
  test('blossom server landing page', async ({ page }) => {
    const response = await page.goto(`https://blossom.${BASE_DOMAIN}/`, {
      waitUntil: 'networkidle',
      timeout: 15000,
    });
    expect(response).not.toBeNull();
    expect(response!.status()).toBeLessThan(500);
  });

  test('blossom server health check', async ({ request }) => {
    const response = await request.get(`https://blossom.${BASE_DOMAIN}/`, {
      ignoreHTTPSErrors: true,
    });
    expect(response.status()).toBeLessThan(500);
  });
});
