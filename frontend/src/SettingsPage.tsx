import { useEffect, useState, type FormEvent } from 'react';
import { Check, KeyRound, LoaderCircle, Save } from 'lucide-react';
import { api, type Capabilities, type ProviderSettings } from './api';
import { colorThemes, type ColorTheme, type ContrastTheme } from './theme';

type SecretName = 'tencent_secret_id' | 'tencent_secret_key' | 'pose_api_key' | 'seedream_api_key' | 'flux_api_key' | 'flux_max_api_key' | 'flux_klein_api_key' | 'flux_klein_9b_api_key' | 'gpt_image_api_key' | 'faceverse_api_key' | 'unsplash_access_key' | 'pixabay_api_key';
type PlainName = 'tencent_endpoint' | 'tencent_region' | 'tencent_model' | 'pose_endpoint' | 'pose_model' | 'seedream_endpoint' | 'seedream_model' | 'flux_endpoint' | 'flux_model' | 'flux_max_endpoint' | 'flux_max_model' | 'flux_klein_endpoint' | 'flux_klein_model' | 'flux_klein_9b_endpoint' | 'flux_klein_9b_model' | 'gpt_image_endpoint' | 'gpt_image_model' | 'faceverse_endpoint' | 'faceverse_model' | 'image_provider';
const secretNames: SecretName[] = ['tencent_secret_id', 'tencent_secret_key', 'pose_api_key', 'seedream_api_key', 'flux_api_key', 'flux_max_api_key', 'flux_klein_api_key', 'flux_klein_9b_api_key', 'gpt_image_api_key', 'faceverse_api_key', 'unsplash_access_key', 'pixabay_api_key'];
const plainNames: PlainName[] = ['tencent_endpoint', 'tencent_region', 'tencent_model', 'pose_endpoint', 'pose_model', 'seedream_endpoint', 'seedream_model', 'flux_endpoint', 'flux_model', 'flux_max_endpoint', 'flux_max_model', 'flux_klein_endpoint', 'flux_klein_model', 'flux_klein_9b_endpoint', 'flux_klein_9b_model', 'gpt_image_endpoint', 'gpt_image_model', 'faceverse_endpoint', 'faceverse_model', 'image_provider'];
const imageProviders: { id: string; label: string }[] = [
  { id: 'so', label: '360 图片 · 免 key（默认）' },
  { id: 'unsplash', label: 'Unsplash · 需 Access Key' },
  { id: 'pixabay', label: 'Pixabay · 需 API Key' },
];

function SecretInput({ label, name, configured, value, clear, onValue, onClear }: {
  label: string; name: SecretName; configured: boolean; value: string; clear: boolean;
  onValue: (name: SecretName, value: string) => void;
  onClear: (name: SecretName, value: boolean) => void;
}) {
  return <div className="settings-secret"><div className="settings-label-row"><label htmlFor={name}>{label}</label>
    <span className={configured ? 'settings-ready' : 'muted'}>{configured ? '已保存' : '未填写'}</span></div>
    <input id={name} className="text-input" type="password" autoComplete="new-password"
      value={value} disabled={clear} placeholder={configured ? '留空则保留已保存的密钥' : '输入密钥'}
      onChange={(event) => onValue(name, event.target.value)} />
    {configured && <label className="settings-clear"><input type="checkbox" checked={clear}
      onChange={(event) => onClear(name, event.target.checked)} />清除已保存的{label}</label>}
  </div>;
}

export function SettingsPage({ onCapabilities, colorTheme, contrastTheme, onColorTheme, onContrastTheme }: {
  onCapabilities: (value: Capabilities) => void;
  colorTheme: ColorTheme; contrastTheme: ContrastTheme;
  onColorTheme: (value: ColorTheme) => void; onContrastTheme: (value: ContrastTheme) => void;
}) {
  const [settings, setSettings] = useState<ProviderSettings | null>(null);
  const [savedSettings, setSavedSettings] = useState<ProviderSettings | null>(null);
  const [secrets, setSecrets] = useState<Record<SecretName, string>>({
    tencent_secret_id: '', tencent_secret_key: '', pose_api_key: '', seedream_api_key: '', flux_api_key: '', flux_max_api_key: '', flux_klein_api_key: '', flux_klein_9b_api_key: '', gpt_image_api_key: '', faceverse_api_key: '', unsplash_access_key: '', pixabay_api_key: '',
  });
  const [cleared, setCleared] = useState<Record<SecretName, boolean>>({
    tencent_secret_id: false, tencent_secret_key: false, pose_api_key: false, seedream_api_key: false, flux_api_key: false, flux_max_api_key: false, flux_klein_api_key: false, flux_klein_9b_api_key: false, gpt_image_api_key: false, faceverse_api_key: false, unsplash_access_key: false, pixabay_api_key: false,
  });
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    let active = true;
    api<ProviderSettings>('/api/settings').then((value) => {
      if (active) { setSettings(value); setSavedSettings(value); }
    }).catch((err) => { if (active) setError((err as Error).message); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, []);

  function edit(name: PlainName, value: string) {
    setSettings((current) => current ? { ...current, [name]: value } : current);
    setSaved(false);
  }
  function editSecret(name: SecretName, value: string) {
    setSecrets((current) => ({ ...current, [name]: value }));
    setSaved(false);
  }
  function clearSecret(name: SecretName, value: boolean) {
    setCleared((current) => ({ ...current, [name]: value }));
    setSaved(false);
  }
  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!settings || !savedSettings || saving) return;
    setSaving(true); setError(''); setSaved(false);
    const payload: Record<string, string> = {};
    for (const name of plainNames) {
      // An older backend may not expose every field yet; skip what it does not send.
      const value = settings[name];
      if (typeof value !== 'string') continue;
      const trimmed = value.trim();
      if (trimmed !== savedSettings[name]) payload[name] = trimmed;
    }
    for (const name of secretNames) {
      if (cleared[name]) payload[name] = '';
      else if (secrets[name]) payload[name] = secrets[name];
    }
    try {
      const updated = await api<ProviderSettings>('/api/settings', {
        method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
      });
      setSettings(updated);
      setSavedSettings(updated);
      setSecrets({ tencent_secret_id: '', tencent_secret_key: '', pose_api_key: '', seedream_api_key: '', flux_api_key: '', flux_max_api_key: '', flux_klein_api_key: '', flux_klein_9b_api_key: '', gpt_image_api_key: '', faceverse_api_key: '', unsplash_access_key: '', pixabay_api_key: '' });
      setCleared({ tencent_secret_id: false, tencent_secret_key: false, pose_api_key: false, seedream_api_key: false, flux_api_key: false, flux_max_api_key: false, flux_klein_api_key: false, flux_klein_9b_api_key: false, gpt_image_api_key: false, faceverse_api_key: false, unsplash_access_key: false, pixabay_api_key: false });
      onCapabilities(await api<Capabilities>('/api/capabilities'));
      setSaved(true);
    } catch (err) { setError((err as Error).message); }
    finally { setSaving(false); }
  }

  const appearance = <section className="settings-section theme-section"><div className="settings-section-title"><span>外观</span><div><h3>工作台主题</h3><p>选择适合你的配色与对比度，修改会立即生效并保存在浏览器中。</p></div></div>
      <div className="theme-controls"><div><strong>配色</strong><div className="theme-options" role="radiogroup" aria-label="配色主题">{colorThemes.map((option) =>
        <button type="button" key={option.id} role="radio" aria-checked={colorTheme === option.id}
          className={`theme-choice ${colorTheme === option.id ? 'active' : ''}`} onClick={() => onColorTheme(option.id)}>
          <span className={`theme-swatch theme-swatch-${option.id}`} /><span><b>{option.label}</b><small>{option.description}</small></span></button>)}</div></div>
        <div><strong>对比度</strong><div className="contrast-options" role="radiogroup" aria-label="对比度主题">
          <button type="button" role="radio" aria-checked={contrastTheme === 'standard'} className={contrastTheme === 'standard' ? 'active' : ''}
            onClick={() => onContrastTheme('standard')}>标准对比度</button>
          <button type="button" role="radio" aria-checked={contrastTheme === 'high'} className={contrastTheme === 'high' ? 'active' : ''}
            onClick={() => onContrastTheme('high')}>高对比度</button></div></div></div></section>;

  if (loading) return <main className="settings-page">{appearance}<p className="muted">正在读取服务配置…</p></main>;
  if (!settings) return <main className="settings-page">{appearance}<p role="alert" className="settings-error">{error}</p></main>;

  return <main className="settings-page">{appearance}<div className="settings-intro"><KeyRound size={22} />
    <div><h2>模型服务</h2><p>填写账号信息后即可使用生成服务。密钥保存在本机，页面不会显示已保存的密钥。</p></div></div>
    <form onSubmit={(event) => void save(event)}>
      <section className="settings-section"><div className="settings-section-title"><span>01</span><div><h3>腾讯云混元 AI3D</h3><p>用于 3D 生成、拓扑、纹理、绑骨与 FBX 转换</p></div></div>
        <div className="settings-fields"><label htmlFor="tencent_endpoint">服务地址</label>
          <input id="tencent_endpoint" className="text-input" value={settings.tencent_endpoint}
            placeholder="ai3d.tencentcloudapi.com" onChange={(event) => edit('tencent_endpoint', event.target.value)} />
          <div className="settings-field"><label htmlFor="tencent_region">地域</label>
            <input id="tencent_region" className="text-input" value={settings.tencent_region}
              placeholder="例如 ap-guangzhou" onChange={(event) => edit('tencent_region', event.target.value)} /></div>
          <div className="settings-field"><label htmlFor="tencent_model">模型版本</label>
            <input id="tencent_model" className="text-input" value={settings.tencent_model}
              onChange={(event) => edit('tencent_model', event.target.value)} /></div>
          <SecretInput label="Secret ID" name="tencent_secret_id" configured={settings.tencent_secret_id_set}
            value={secrets.tencent_secret_id} clear={cleared.tencent_secret_id} onValue={editSecret} onClear={clearSecret} />
          <SecretInput label="Secret Key" name="tencent_secret_key" configured={settings.tencent_secret_key_set}
            value={secrets.tencent_secret_key} clear={cleared.tencent_secret_key} onValue={editSecret} onClear={clearSecret} />
        </div></section>
      <section className="settings-section"><div className="settings-section-title"><span>02</span><div><h3>阿里云千问图像编辑</h3><p>用于 A-Pose、T-Pose 和自定义姿势编辑</p></div></div>
        <div className="settings-fields"><label htmlFor="pose_endpoint">服务地址</label>
          <input id="pose_endpoint" className="text-input" value={settings.pose_endpoint}
            placeholder="北京业务空间的完整 HTTPS URL" onChange={(event) => edit('pose_endpoint', event.target.value)} />
          <p className="settings-field-hint">填写北京业务空间地址，路径以 /api/v1/services/aigc/multimodal-generation/generation 结尾。</p>
          <div className="settings-field settings-field-full"><label htmlFor="pose_model">模型</label>
            <input id="pose_model" className="text-input" value={settings.pose_model}
              onChange={(event) => edit('pose_model', event.target.value)} /></div>
          <SecretInput label="API Key" name="pose_api_key" configured={settings.pose_api_key_set}
            value={secrets.pose_api_key} clear={cleared.pose_api_key} onValue={editSecret} onClear={clearSecret} />
        </div></section>
      <section className="settings-section"><div className="settings-section-title"><span>03</span><div><h3>火山引擎 SeedDream 5.0</h3><p>用于独立虚拟试穿页面的六视图换装</p></div></div>
        <div className="settings-fields"><div className="settings-field settings-field-full"><label htmlFor="seedream_endpoint">服务地址</label>
          <input id="seedream_endpoint" className="text-input" value={settings.seedream_endpoint}
            placeholder="https://ark.cn-beijing.volces.com/api/v3/images/generations" onChange={(event) => edit('seedream_endpoint', event.target.value)} /></div>
          <div className="settings-field settings-field-full"><label htmlFor="seedream_model">模型 ID</label>
            <input id="seedream_model" className="text-input" value={settings.seedream_model}
              onChange={(event) => edit('seedream_model', event.target.value)} /></div>
          <SecretInput label="API Key" name="seedream_api_key" configured={settings.seedream_api_key_set}
            value={secrets.seedream_api_key} clear={cleared.seedream_api_key} onValue={editSecret} onClear={clearSecret} />
        </div></section>
      <section className="settings-section"><div className="settings-section-title"><span>04</span><div><h3>FLUX.2 Pro</h3><p>支持官方 BFL 或海鲸多参考图试验接口；海鲸实际效果需测试</p></div></div>
        <div className="settings-fields"><div className="settings-field settings-field-full"><label htmlFor="flux_endpoint">服务地址</label>
          <input id="flux_endpoint" className="text-input" value={settings.flux_endpoint}
            placeholder="https://api.bfl.ai/v1/flux-2-pro" onChange={(event) => edit('flux_endpoint', event.target.value)} /></div>
          <div className="settings-field settings-field-full"><label htmlFor="flux_model">模型标识</label>
            <input id="flux_model" className="text-input" value={settings.flux_model}
              onChange={(event) => edit('flux_model', event.target.value)} /></div>
          <SecretInput label="API Key" name="flux_api_key" configured={settings.flux_api_key_set}
            value={secrets.flux_api_key} clear={cleared.flux_api_key} onValue={editSecret} onClear={clearSecret} /></div></section>
      <section className="settings-section"><div className="settings-section-title"><span>05</span><div><h3>FLUX.2 Max</h3><p>支持官方 BFL 或海鲸多参考图试验接口；海鲸实际效果需测试</p></div></div>
        <div className="settings-fields"><div className="settings-field settings-field-full"><label htmlFor="flux_max_endpoint">服务地址</label>
          <input id="flux_max_endpoint" className="text-input" value={settings.flux_max_endpoint ?? ''}
            placeholder="https://api.bfl.ai/v1/flux-2-max" onChange={(event) => edit('flux_max_endpoint', event.target.value)} /></div>
          <div className="settings-field settings-field-full"><label htmlFor="flux_max_model">模型标识</label>
            <input id="flux_max_model" className="text-input" value={settings.flux_max_model ?? 'flux-2-max'}
              onChange={(event) => edit('flux_max_model', event.target.value)} /></div>
          <SecretInput label="API Key" name="flux_max_api_key" configured={settings.flux_max_api_key_set}
            value={secrets.flux_max_api_key} clear={cleared.flux_max_api_key} onValue={editSecret} onClear={clearSecret} /></div></section>
      <section className="settings-section"><div className="settings-section-title"><span>06</span><div><h3>FLUX.2 Klein 4B · 自建服务</h3><p>通过独立 FastAPI 服务执行本地权重推理，最多四张参考图</p></div></div>
        <div className="settings-fields"><div className="settings-field settings-field-full"><label htmlFor="flux_klein_endpoint">服务接口地址</label>
          <input id="flux_klein_endpoint" className="text-input" value={settings.flux_klein_endpoint}
            placeholder="http://127.0.0.1:8788/v1/flux-klein/edit" onChange={(event) => edit('flux_klein_endpoint', event.target.value)} /></div>
          <p className="settings-field-hint">本机 SSH 隧道可使用 HTTP；公网地址必须使用 HTTPS。</p>
          <div className="settings-field settings-field-full"><label htmlFor="flux_klein_model">模型标识</label>
            <input id="flux_klein_model" className="text-input" value={settings.flux_klein_model}
              onChange={(event) => edit('flux_klein_model', event.target.value)} /></div>
          <SecretInput label="访问令牌" name="flux_klein_api_key" configured={settings.flux_klein_api_key_set}
            value={secrets.flux_klein_api_key} clear={cleared.flux_klein_api_key} onValue={editSecret} onClear={clearSecret} /></div></section>
      <section className="settings-section"><div className="settings-section-title"><span>07</span><div><h3>FLUX.2 Klein 9B · 自建服务</h3><p>支持多参考图换装，使用独立的 9B 推理服务</p></div></div>
        <div className="settings-fields"><div className="settings-field settings-field-full"><label htmlFor="flux_klein_9b_endpoint">服务接口地址</label>
          <input id="flux_klein_9b_endpoint" className="text-input" value={settings.flux_klein_9b_endpoint ?? ''}
            placeholder="http://127.0.0.1:8789/v1/flux-klein/edit" onChange={(event) => edit('flux_klein_9b_endpoint', event.target.value)} /></div>
          <p className="settings-field-hint">本机 SSH 隧道可使用 HTTP；公网地址必须使用 HTTPS。</p>
          <div className="settings-field settings-field-full"><label htmlFor="flux_klein_9b_model">模型标识</label>
            <input id="flux_klein_9b_model" className="text-input" value={settings.flux_klein_9b_model ?? 'flux.2-klein-9b'}
              onChange={(event) => edit('flux_klein_9b_model', event.target.value)} /></div>
          <SecretInput label="访问令牌" name="flux_klein_9b_api_key" configured={settings.flux_klein_9b_api_key_set}
            value={secrets.flux_klein_9b_api_key} clear={cleared.flux_klein_9b_api_key} onValue={editSecret} onClear={clearSecret} /></div></section>
      <section className="settings-section"><div className="settings-section-title"><span>08</span><div><h3>GPT Image 2</h3><p>多图编辑；可填写官方接口或兼容的 HTTPS 服务地址</p></div></div>
        <div className="settings-fields"><div className="settings-field settings-field-full"><label htmlFor="gpt_image_endpoint">服务地址</label>
          <input id="gpt_image_endpoint" className="text-input" value={settings.gpt_image_endpoint}
            placeholder="https://api.openai.com/v1/images/edits" onChange={(event) => edit('gpt_image_endpoint', event.target.value)} /></div>
          <div className="settings-field settings-field-full"><label htmlFor="gpt_image_model">模型 ID</label>
            <input id="gpt_image_model" className="text-input" value={settings.gpt_image_model}
              onChange={(event) => edit('gpt_image_model', event.target.value)} /></div>
          <SecretInput label="API Key" name="gpt_image_api_key" configured={settings.gpt_image_api_key_set}
            value={secrets.gpt_image_api_key} clear={cleared.gpt_image_api_key} onValue={editSecret} onClear={clearSecret} /></div></section>
      <section className="settings-section"><div className="settings-section-title"><span>09</span><div><h3>FaceVerse 远程服务器</h3><p>用于 3D 完成后的高精度头脸重建与网格融合；未配置时不影响原流程</p></div></div>
        <div className="settings-fields"><div className="settings-field settings-field-full"><label htmlFor="faceverse_endpoint">服务器接口地址</label>
          <input id="faceverse_endpoint" className="text-input" value={settings.faceverse_endpoint}
            placeholder="https://your-server.example.cn/v1/face-refine" onChange={(event) => edit('faceverse_endpoint', event.target.value)} /></div>
          <p className="settings-field-hint">公网服务器需使用 HTTPS；本机测试可使用 http://127.0.0.1:端口/v1/face-refine。</p>
          <div className="settings-field settings-field-full"><label htmlFor="faceverse_model">服务器模型标识</label>
            <input id="faceverse_model" className="text-input" value={settings.faceverse_model}
              onChange={(event) => edit('faceverse_model', event.target.value)} /></div>
          <SecretInput label="访问令牌（可选）" name="faceverse_api_key" configured={settings.faceverse_api_key_set}
            value={secrets.faceverse_api_key} clear={cleared.faceverse_api_key} onValue={editSecret} onClear={clearSecret} />
        </div></section>
      <section className="settings-section"><div className="settings-section-title"><span>10</span><div><h3>穿搭图片检索</h3><p>为穿搭推荐获取真实穿搭图片；默认使用免 key 的 360 图片，可切换到自主图库账号</p></div></div>
        <div className="settings-fields"><div className="settings-field settings-field-full"><label htmlFor="image_provider">图片来源</label>
          <select id="image_provider" className="text-input" value={settings.image_provider}
            onChange={(event) => edit('image_provider', event.target.value)}>
            {imageProviders.map((option) => <option key={option.id} value={option.id}>{option.label}</option>)}
          </select></div>
          <p className="settings-field-hint">360 图片免 key、中文相关度高；Unsplash 与 Pixabay 图片授权更清晰，需要自备密钥。检索结果缓存在本机，页面保留来源链接。</p>
          <SecretInput label="Unsplash Access Key" name="unsplash_access_key" configured={settings.unsplash_access_key_set}
            value={secrets.unsplash_access_key} clear={cleared.unsplash_access_key} onValue={editSecret} onClear={clearSecret} />
          <SecretInput label="Pixabay API Key" name="pixabay_api_key" configured={settings.pixabay_api_key_set}
            value={secrets.pixabay_api_key} clear={cleared.pixabay_api_key} onValue={editSecret} onClear={clearSecret} />
        </div></section>
      <div className="settings-footer"><p>保存后立即生效。服务显示“已配置”仅代表必填项齐全，实际调用仍取决于账号权限。</p>
        {error && <p className="settings-error" role="alert">{error}</p>}
        {saved && <p className="settings-success" role="status"><Check size={15} /> 配置已保存并生效</p>}
        <button className="button settings-save" type="submit" disabled={saving}>
          {saving ? <LoaderCircle className="spin" size={16} /> : <Save size={16} />}保存设置</button></div>
    </form></main>;
}
