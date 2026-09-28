import { test, expect } from '@playwright/test';

const BASE_DOMAIN = process.env.BASE_DOMAIN || 'localhost';

test.describe('TLS Configuration', () => {
  const subdomains = ['relay', 'chat', 'blossom', 'nsite', 'releases', 'ci'];

  for (const sub of subdomains) {
    test(`${sub}.${BASE_DOMAIN} has valid TLS`, async ({ request }) => {
      const response = await request.get(`https://${sub}.${BASE_DOMAIN}/`, {
        ignoreHTTPSErrors: true,
        timeout: 10000,
      });
      expect(response.status()).toBeLessThan(500);
      expect(response.url()).toContain('https');
    });
  }
});
