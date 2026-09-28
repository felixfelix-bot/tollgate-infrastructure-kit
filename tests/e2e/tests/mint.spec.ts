import { test, expect } from '@playwright/test';

const BASE_DOMAIN = process.env.BASE_DOMAIN || 'localhost';

test.describe('Cashu Mint Infrastructure', () => {
  test('mint wildcard subdomain resolves', async ({ request }) => {
    const response = await request.get(`https://test.mints.${BASE_DOMAIN}/`, {
      ignoreHTTPSErrors: true,
      timeout: 10000,
    });
    expect(response.status()).toBeLessThan(500);
  });
});
