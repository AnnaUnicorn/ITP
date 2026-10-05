import { readFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { expect, test, type Page } from '@playwright/test';

const dist = fileURLToPath(new URL('../dist/', import.meta.url));
const caps = {
  geometry: false, pose: false, segmentation: false, tryon: false, tryon_model: '',
  tryon_providers: { seedream: false, flux: false, flux_max: false, flux_klein: true,
    flux_klein_9b: true, gpt_image: false },
  faceverse: false, faceverse_model: '', outfit_images: false, image_provider: 'so',
  provider: '', pose_provider: '', model: '3.1', pose_model: '',
};

async function serveBundle(page: Page) {
  await page.route('**/*', async (route) => {
    const pathname = new URL(route.request().url()).pathname;
    if (pathname === '/') {
      await route.fulfill({ body: await readFile(`${dist}/index.html`), contentType: 'text/html' });
    } else if (pathname.startsWith('/assets/')) {
      const name = pathname.slice('/assets/'.length);
      if (!/^[\w.-]+$/.test(name)) { await route.fulfill({ status: 404 }); return; }
      await route.fulfill({ body: await readFile(`${dist}/assets/${name}`),
        contentType: name.endsWith('.css') ? 'text/css' : 'text/javascript' });
    } else if (pathname === '/api/capabilities') {
      await route.fulfill({ json: caps });
    } else if (pathname === '/api/jobs' || pathname === '/api/tryons') {
      await route.fulfill({ json: [] });
    } else {
      await route.fulfill({ status: 404 });
    }
  });
}

test('Klein selection uses independent health and submits the 9B provider', async ({ page }) => {
  await serveBundle(page);
  let resolveHealth!: () => void;
  const pendingHealth = new Promise<void>((resolve) => { resolveHealth = resolve; });
  await page.route('**/api/tryon-providers/flux-klein/health', (route) =>
    route.fulfill({ json: { ready: true, model: 'flux.2-klein-4b' } }));
  await page.route('**/api/tryon-providers/flux-klein-9b/health', async (route) => {
    await pendingHealth;
    await route.fulfill({ json: { ready: true, model: 'flux.2-klein-9b' } });
  });
  const asset = { id: 'a'.repeat(32), url: '', kind: 'image', size: 100 };
  await page.addInitScript((value) => {
    sessionStorage.setItem('itp-tryon-person', JSON.stringify({ front: value }));
    sessionStorage.setItem('itp-tryon-garment', JSON.stringify({ front: value }));
  }, asset);
  let submitted: Record<string, unknown> | undefined;
  await page.route('**/api/tryons', async (route) => {
    if (route.request().method() === 'POST') {
      submitted = route.request().postDataJSON();
      await route.fulfill({ json: { id: 'b'.repeat(32), name: '虚拟试穿', state: 'ready',
        model: 'flux.2-klein-9b', provider: 'flux_klein_9b', results: {}, active_view: null } });
    } else {
      await route.fulfill({ json: [] });
    }
  });
  await page.goto('/');
  await page.getByRole('button', { name: '虚拟试穿', exact: true }).click();
  const picker = page.locator('select:visible').first();
  const generate = page.getByRole('button', { name: '生成六视图试穿' });
  await picker.selectOption('flux_klein');
  await expect(generate).toBeEnabled();
  await picker.selectOption('flux_klein_9b');
  await expect(generate).toBeDisabled();
  resolveHealth();
  await expect(generate).toBeEnabled();
  await generate.click();
  await expect.poll(() => submitted?.provider).toBe('flux_klein_9b');
  expect(submitted?.person).toEqual({ front: asset.id });
  expect(submitted?.garment).toEqual({ front: asset.id });
});

test('9B settings save only their own endpoint and token', async ({ page }) => {
  await serveBundle(page);
  const settings: Record<string, unknown> = {
    tencent_endpoint: '', tencent_region: '', tencent_model: '3.1',
    pose_endpoint: '', pose_model: '', seedream_endpoint: '', seedream_model: '',
    flux_endpoint: '', flux_model: '', flux_klein_endpoint: 'http://127.0.0.1:8788/v1/flux-klein/edit',
    flux_max_endpoint: '', flux_max_model: 'flux-2-max', flux_max_api_key_set: false,
    flux_klein_model: 'flux.2-klein-4b', flux_klein_api_key_set: true,
    flux_klein_9b_endpoint: '', flux_klein_9b_model: 'flux.2-klein-9b',
    flux_klein_9b_api_key_set: false, gpt_image_endpoint: '', gpt_image_model: '',
    faceverse_endpoint: '', faceverse_model: '', image_provider: 'so',
  };
  let submitted: Record<string, unknown> | undefined;
  await page.route('**/api/settings', async (route) => {
    if (route.request().method() === 'PATCH') {
      submitted = route.request().postDataJSON();
      settings.flux_klein_9b_endpoint = submitted?.flux_klein_9b_endpoint;
      settings.flux_klein_9b_api_key_set = true;
    }
    await route.fulfill({ json: settings });
  });
  await page.goto('/');
  await page.getByRole('button', { name: '设置', exact: true }).click();
  await page.locator('#flux_klein_9b_endpoint').fill('http://127.0.0.1:8789/v1/flux-klein/edit');
  await page.locator('#flux_klein_9b_api_key').fill('test-9b-token');
  await page.getByRole('button', { name: '保存设置' }).click();
  await expect(page.getByText('配置已保存并生效')).toBeVisible();
  expect(submitted).toEqual({ flux_klein_9b_endpoint: 'http://127.0.0.1:8789/v1/flux-klein/edit',
    flux_klein_9b_api_key: 'test-9b-token' });
  await expect(page.locator('#flux_klein_9b_api_key')).toHaveValue('');
  await expect(page.locator('#flux_klein_endpoint')).toHaveValue(settings.flux_klein_endpoint as string);
});
