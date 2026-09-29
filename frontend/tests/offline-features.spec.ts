import { readFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { expect, test, type Page } from '@playwright/test';

const dist = fileURLToPath(new URL('../dist/', import.meta.url));
const image = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/lXcAAAAASUVORK5CYII=', 'base64');

async function openStudio(page: Page, jobs: unknown[] = []) {
  await page.route('**/*', async (route) => {
    const request = route.request();
    const pathname = new URL(request.url()).pathname;
    if (pathname === '/api/capabilities') {
      await route.fulfill({ json: { geometry: false, pose: false, segmentation: false,
        provider: '', pose_provider: '', model: '3.1', pose_model: '' } });
    } else if (pathname === '/api/jobs') {
      await route.fulfill({ json: jobs });
    } else if (pathname === '/api/settings') {
      await route.fulfill({ json: { tencent_endpoint: '', tencent_region: '', tencent_model: '3.1',
        tencent_secret_id_set: false, tencent_secret_key_set: false, pose_endpoint: '',
        pose_model: 'qwen-image-edit-plus-2025-12-15', pose_api_key_set: false } });
    } else if (pathname.startsWith('/api/assets') && request.method() === 'POST') {
      await route.fulfill({ status: 201, json: { id: 'a'.repeat(32), url: `data:image/png;base64,${image.toString('base64')}`,
        kind: 'image', width: 256, height: 256, size: image.length } });
    } else if (pathname === '/') {
      await route.fulfill({ body: await readFile(`${dist}/index.html`), contentType: 'text/html' });
    } else if (pathname.startsWith('/assets/')) {
      const name = pathname.slice('/assets/'.length);
      if (!/^[\w.-]+$/.test(name)) { await route.fulfill({ status: 404 }); return; }
      await route.fulfill({ body: await readFile(`${dist}/assets/${name}`),
        contentType: name.endsWith('.css') ? 'text/css' : 'text/javascript' });
    } else {
      await route.fulfill({ status: 404 });
    }
  });
  await page.goto('/');
}

test('generate checklist and uploaded image preview', async ({ page }) => {
  await openStudio(page);
  await page.getByRole('button', { name: '开始生成' }).click();
  await expect(page.getByText('请上传角色图片')).toBeVisible();
  await page.getByLabel('上传上传角色图片').setInputFiles({
    name: 'character.png', mimeType: 'image/png', buffer: image,
  });
  await expect(page.getByText('请上传角色图片')).toHaveCount(0);
  await page.getByRole('button', { name: '放大查看上传角色图片' }).click();
  await expect(page.getByRole('dialog', { name: '预览上传角色图片' })).toBeVisible();
  await page.getByRole('button', { name: '关闭图片预览' }).click();
  await expect(page.getByRole('dialog', { name: '预览上传角色图片' })).toHaveCount(0);
  await page.getByRole('button', { name: '自定义' }).click();
  await expect(page.getByText('请上传姿势参考图')).toBeVisible();
  await page.getByLabel('几何目标面数').selectOption('1500000');
  await expect(page.getByLabel('几何目标面数')).toHaveValue('1500000');
});

test('color and contrast themes persist after reload', async ({ page }) => {
  await openStudio(page);
  await page.getByRole('button', { name: '设置', exact: true }).click();
  await page.getByRole('radio', { name: /海洋蓝/ }).click();
  await page.getByRole('radio', { name: '高对比度' }).click();
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'ocean');
  await expect(page.locator('html')).toHaveAttribute('data-contrast', 'high');
  await page.reload();
  await page.getByRole('button', { name: '设置', exact: true }).click();
  await expect(page.getByRole('radio', { name: /海洋蓝/ })).toHaveAttribute('aria-checked', 'true');
  await expect(page.getByRole('radio', { name: '高对比度' })).toHaveAttribute('aria-checked', 'true');
});

test('old provider error displays a useful explanation', async ({ page }) => {
  await openStudio(page, [{
    id: 'b'.repeat(32), name: '失败任务', state: 'failed', created: 1790671818,
    error: '腾讯云错误 ResourceUnavailable.NotExist；RequestId=request-123',
    request: { front: 'a'.repeat(32), pose_mode: 'original', topology: false,
      texture: false, rig: false, export_fbx: false }, pose_asset: null,
    steps: [{ name: 'geometry', status: 'failed' }], artifacts: [],
  }]);
  await page.getByRole('button', { name: '任务记录' }).click();
  await page.getByRole('button', { name: /失败任务/ }).click();
  await expect(page.getByText(/服务未开通或计费状态异常/)).toBeVisible();
});
