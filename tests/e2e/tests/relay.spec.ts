import { test, expect } from '@playwright/test';

const BASE_DOMAIN = process.env.BASE_DOMAIN || 'localhost';

test.describe('Nostr Relay (strfry)', () => {
  test('relay WebSocket endpoint responds', async ({ request }) => {
    const response = await request.get(`https://relay.${BASE_DOMAIN}`, {
      ignoreHTTPSErrors: true,
    });
    expect(response.status()).toBeLessThan(500);
  });

  test('relay NIP-11 info document', async ({ request }) => {
    const response = await request.get(`https://relay.${BASE_DOMAIN}`, {
      headers: { Accept: 'application/nostr+json' },
      ignoreHTTPSErrors: true,
    });
    if (response.status() === 200) {
      const body = await response.json();
      expect(body).toHaveProperty('name');
    }
  });
});
