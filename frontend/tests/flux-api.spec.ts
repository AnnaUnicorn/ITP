import { readFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { expect, test } from '@playwright/test';

const dist = fileURLToPath(new URL('../dist/', import.meta.url));

for (const [provider, model, label, relay] of [
  ['flux', 'flux-2-pro', 'FLUX.2 Pro', false],
  ['flux_max', 'flux-2-max', 'FLUX.2 Max', false],
  ['flux', 'flux-2-pro', 'FLUX.2 Pro', true],
  ['flux_max', 'flux-2-max', 'FLUX.2 Max', true],
] as const) {
  test(`${label} ${relay ? 'relay' : 'BFL'} saves its own API configuration safely`, async ({ page }) => {
    const endpoint = relay ? 'https://api.haijingai.com/v2/images/generations' : `https://api.bfl.ai/v1/${model}`;
    const settings: Record<string, string | boolean> = {
      tencent_endpoint: '', tencent_region: '', tencent_model: '3.1',
      pose_endpoint: '', pose_model: '', seedream_endpoint: '', seedream_model: '',
      flux_endpoint: '', flux_model: 'flux-2-pro', flux_api_key_set: false,
      flux_max_endpoint: '', flux_max_model: 'flux-2-max', flux_max_api_key_set: false,
      flux_klein_endpoint: '', flux_klein_model: 'flux.2-klein-4b',
      flux_klein_9b_endpoint: '', flux_klein_9b_model: 'flux.2-klein-9b',
      gpt_image_endpoint: '', gpt_image_model: '', faceverse_endpoint: '', faceverse_model: '',
      image_provider: 'so',
    };
    let saved: Record<string, string> | undefined;
    let submitted: Record<string, unknown> | undefined;
    await page.route('**/*', async (route) => {
      const request = route.request();
      const pathname = new URL(request.url()).pathname;
      if (pathname === '/') {
        await route.fulfill({ body: await readFile(`${dist}/index.html`), contentType: 'text/html' });
      } else if (pathname.startsWith('/assets/')) {
        const name = pathname.slice('/assets/'.length);
        if (!/^[\w.-]+$/.test(name)) { await route.fulfill({ status: 404 }); return; }
        await route.fulfill({ body: await readFile(`${dist}/assets/${name}`),
          contentType: name.endsWith('.css') ? 'text/css' : 'text/javascript' });
      } else if (pathname === '/api/settings') {
        if (request.method() === 'PATCH') {
          saved = request.postDataJSON();
          Object.assign(settings, saved);
          settings[`${provider}_api_key_set`] = true;
          delete settings[`${provider}_api_key`];
        }
        await route.fulfill({ json: settings });
      } else if (pathname === '/api/capabilities') {
        await route.fulfill({ json: {
          geometry: false, pose: false, segmentation: false, tryon: false, tryon_model: '',
          tryon_providers: { seedream: false, flux: settings.flux_api_key_set,
            flux_max: settings.flux_max_api_key_set, flux_klein: false,
            flux_klein_9b: false, gpt_image: false },
          faceverse: false, faceverse_model: '', outfit_images: false, image_provider: 'so',
          provider: '', pose_provider: '', model: '3.1', pose_model: '',
        } });
      } else if (pathname === '/api/tryons' && request.method() === 'POST') {
        submitted = request.postDataJSON();
        await route.fulfill({ json: { id: 'b'.repeat(32), name: '虚拟试穿', state: 'ready',
          model, provider, results: {}, active_view: null } });
      } else if (pathname === '/api/jobs' || pathname === '/api/tryons') {
        await route.fulfill({ json: [] });
      } else {
        await route.fulfill({ status: 404 });
      }
    });
    const asset = { id: 'a'.repeat(32), url: '', kind: 'image', size: 100 };
    await page.addInitScript((value) => {
      sessionStorage.setItem('itp-tryon-person', JSON.stringify({ front: value }));
      sessionStorage.setItem('itp-tryon-garment', JSON.stringify({ front: value }));
    }, asset);
    await page.goto('/');
    await page.getByRole('button', { name: '虚拟试穿', exact: true }).click();
    const picker = page.locator('select:visible').first();
    await expect(picker.locator('option', { hasText: 'FLUX.2 Pro' })).toHaveCount(1);
    await expect(picker.locator('option', { hasText: 'FLUX.2 Max' })).toHaveCount(1);
    await picker.selectOption(provider);
    await expect(page.getByRole('button', { name: '生成六视图试穿' })).toBeDisabled();
    await page.getByRole('button', { name: '设置', exact: true }).click();
    await expect(page.getByRole('heading', { name: label, exact: true })).toBeVisible();
    await expect(page.locator(`#${provider}_model`)).toHaveValue(model);
    await page.locator(`#${provider}_endpoint`).fill(endpoint);
    await page.locator(`#${provider}_api_key`).fill('test-api-key');
    await page.getByRole('button', { name: '保存设置' }).click();
    await expect(page.getByText('配置已保存并生效')).toBeVisible();
    expect(saved).toEqual({ [`${provider}_endpoint`]: endpoint,
      [`${provider}_api_key`]: 'test-api-key' });
    await expect(page.locator(`#${provider}_api_key`)).toHaveValue('');
    await page.getByRole('button', { name: '虚拟试穿', exact: true }).click();
    await page.locator('select:visible').first().selectOption(provider);
    await expect(page.getByRole('button', { name: '生成六视图试穿' })).toBeEnabled();
    await page.getByRole('button', { name: '生成六视图试穿' }).click();
    await expect.poll(() => submitted?.provider).toBe(provider);
    expect(submitted?.person).toEqual({ front: asset.id });
    expect(submitted?.garment).toEqual({ front: asset.id });
  });
}
