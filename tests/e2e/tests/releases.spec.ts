import { test, expect } from '@playwright/test';

const BASE_DOMAIN = process.env.BASE_DOMAIN || 'localhost';

test.describe('Tollgate Release Explorer', () => {
  test('release explorer loads', async ({ page }) => {
    const response = await page.goto(`https://releases.${BASE_DOMAIN}/`, {
      waitUntil: 'networkidle',
      timeout: 15000,
    });
    expect(response).not.toBeNull();
    expect(response!.status()).toBeLessThan(500);
  });

  test('release explorer has title', async ({ page }) => {
    await page.goto(`https://releases.${BASE_DOMAIN}/`, {
      waitUntil: 'networkidle',
      timeout: 15000,
    });
    const title = await page.title();
    expect(title.toLowerCase()).toContain('tollgate');
  });

  test('release explorer renders content', async ({ page }) => {
    await page.goto(`https://releases.${BASE_DOMAIN}/`, {
      waitUntil: 'networkidle',
      timeout: 15000,
    });
    const body = page.locator('body');
    await expect(body).toBeVisible();
  });
});
