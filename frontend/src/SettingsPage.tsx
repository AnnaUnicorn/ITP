import { useEffect, useState, type FormEvent } from 'react';
import { Check, KeyRound, LoaderCircle, Save } from 'lucide-react';
import { api, type Capabilities, type ProviderSettings } from './api';
import { colorThemes, type ColorTheme, type ContrastTheme } from './theme';

type SecretName = 'tencent_secret_id' | 'tencent_secret_key' | 'pose_api_key';
type PlainName = 'tencent_endpoint' | 'tencent_region' | 'tencent_model' | 'pose_endpoint' | 'pose_model';
const secretNames: SecretName[] = ['tencent_secret_id', 'tencent_secret_key', 'pose_api_key'];
const plainNames: PlainName[] = ['tencent_endpoint', 'tencent_region', 'tencent_model', 'pose_endpoint', 'pose_model'];

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
    tencent_secret_id: '', tencent_secret_key: '', pose_api_key: '',
  });
  const [cleared, setCleared] = useState<Record<SecretName, boolean>>({
    tencent_secret_id: false, tencent_secret_key: false, pose_api_key: false,
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
      const value = settings[name].trim();
      if (value !== savedSettings[name]) payload[name] = value;
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
      setSecrets({ tencent_secret_id: '', tencent_secret_key: '', pose_api_key: '' });
      setCleared({ tencent_secret_id: false, tencent_secret_key: false, pose_api_key: false });
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
      <div className="settings-footer"><p>保存后立即生效。服务显示“已配置”仅代表必填项齐全，实际调用仍取决于账号权限。</p>
        {error && <p className="settings-error" role="alert">{error}</p>}
        {saved && <p className="settings-success" role="status"><Check size={15} /> 配置已保存并生效</p>}
        <button className="button settings-save" type="submit" disabled={saving}>
          {saving ? <LoaderCircle className="spin" size={16} /> : <Save size={16} />}保存设置</button></div>
    </form></main>;
}
