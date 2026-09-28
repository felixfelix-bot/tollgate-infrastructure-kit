import { test, expect } from '@playwright/test';

const BASE_DOMAIN = process.env.BASE_DOMAIN || 'localhost';

test.describe('NIP-29 Group Chat (obelisk-relay)', () => {
  test('chat relay is accessible', async ({ request }) => {
    const response = await request.get(`https://chat.${BASE_DOMAIN}`, {
      ignoreHTTPSErrors: true,
    });
    expect(response.status()).toBeLessThan(500);
  });

  test('chat relay NIP-11 document', async ({ request }) => {
    const response = await request.get(`https://chat.${BASE_DOMAIN}`, {
      headers: { Accept: 'application/nostr+json' },
      ignoreHTTPSErrors: true,
    });
    expect(response.status()).toBeLessThan(500);
  });
});
