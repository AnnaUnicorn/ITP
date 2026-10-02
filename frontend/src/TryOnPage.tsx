import { useEffect, useState } from 'react';
import { ArrowRight, Download, LoaderCircle, Shirt, Sparkles } from 'lucide-react';
import { api, fileUrl, post, type Asset, type Capabilities, type Job, type TryOnJob } from './api';
import './TryOnPage.css';

const views = [
  ['front', '正面'], ['back', '背面'], ['left', '左侧'], ['right', '右侧'],
  ['left_front', '左前 45°'], ['right_front', '右前 45°'],
] as const;

function ImageInput({ label, asset, onChange, onBusy }: {
  label: string; asset?: Asset; onChange: (value?: Asset) => void; onBusy: (busy: boolean) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  async function upload(file?: File) {
    if (!file) return;
    if (file.size > 10 * 1024 * 1024) { setError('图片不能超过 10 MiB'); return; }
    setBusy(true); onBusy(true); setError('');
    try {
      const body = new FormData(); body.append('file', file);
      onChange(await api<Asset>('/api/assets', { method: 'POST', body }));
    } catch (err) { setError((err as Error).message); }
    finally { setBusy(false); onBusy(false); }
  }
  return <div className="tryon-input"><label>{asset && <img src={asset.url} alt="" />}
    {!asset && <span>{busy ? <LoaderCircle className="spin" size={20} /> : <Shirt size={20} />}{label}</span>}
    <input type="file" accept="image/png,image/jpeg,image/webp" aria-label={`上传${label}`}
      disabled={busy} onChange={(event) => { void upload(event.target.files?.[0]); event.target.value = ''; }} />
  </label>{asset && <button type="button" onClick={() => onChange()}>移除</button>}{error && <small role="alert">{error}</small>}</div>;
}

export function TryOnPage({ caps, onContinue, onSettings }: {
  caps: Capabilities | null; onContinue: (job: Job) => void; onSettings: () => void;
}) {
  const [person, setPerson] = useState<Record<string, Asset>>(() => {
    try { return JSON.parse(sessionStorage.getItem('itp-tryon-person') || '{}'); } catch { return {}; }
  });
  const [garment, setGarment] = useState<Record<string, Asset>>(() => {
    try { return JSON.parse(sessionStorage.getItem('itp-tryon-garment') || '{}'); } catch { return {}; }
  });
  const [name, setName] = useState('');
  const [confirmed, setConfirmed] = useState(false);
  const [busyCount, setBusyCount] = useState(0);
  const [submitting, setSubmitting] = useState(false);
  const [current, setCurrent] = useState<TryOnJob | null>(null);
  const [error, setError] = useState('');

  useEffect(() => { sessionStorage.setItem('itp-tryon-person', JSON.stringify(person)); }, [person]);
  useEffect(() => { sessionStorage.setItem('itp-tryon-garment', JSON.stringify(garment)); }, [garment]);
  useEffect(() => {
    void api<TryOnJob[]>('/api/tryons').then((list) => {
      if (list.length) setCurrent((existing) => existing || list[0]);
    }).catch(() => {});
  }, []);

  useEffect(() => {
    if (!current || !['queued', 'running', 'submitting'].includes(current.state)) return;
    const timer = setInterval(() => {
      void api<TryOnJob>(`/api/tryons/${current.id}`).then(setCurrent).catch((err) => setError((err as Error).message));
    }, 3000);
    return () => clearInterval(timer);
  }, [current?.id, current?.state]);

  const complete = views.every(([view]) => person[view] && garment[view]);
  async function generate() {
    if (!complete || !confirmed || busyCount || submitting) return;
    setSubmitting(true); setError('');
    try {
      const job = await post<TryOnJob>('/api/tryons', {
        name: name.trim() || '虚拟试穿', person: Object.fromEntries(views.map(([view]) => [view, person[view].id])),
        garment: Object.fromEntries(views.map(([view]) => [view, garment[view].id])), consistent_confirmed: true,
      });
      setCurrent(job);
    } catch (err) { setError((err as Error).message); }
    finally { setSubmitting(false); }
  }
  async function continue3D() {
    if (!current) return;
    setSubmitting(true); setError('');
    try { onContinue(await post<Job>(`/api/tryons/${current.id}/continue`, {})); }
    catch (err) { setError((err as Error).message); }
    finally { setSubmitting(false); }
  }

  return <main className="tryon-page">
    <div className="tryon-intro"><Shirt size={28} /><div><h2>六视图虚拟试穿</h2><p>上传同一人物和同一件衣服的六个角度。SeedDream 5.0 分六次换装，生成结果可直接保存，或一键送入 3D 建模。</p></div></div>
    {!caps?.tryon && <div className="tryon-notice">SeedDream 尚未配置。可以先上传图片，之后在<button type="button" onClick={onSettings}>服务设置</button>填写国内火山引擎地址与 API Key。</div>}
    <label className="field-label" htmlFor="tryon-name">任务名称</label><input id="tryon-name" className="text-input" value={name} maxLength={80}
      placeholder="例如：夏季外套试穿" onChange={(event) => setName(event.target.value)} />
    <div className="tryon-groups">{([['人物六面图', person, setPerson], ['衣服六面图', garment, setGarment]] as const).map(([title, items, setter]) =>
      <section key={title}><h3>{title}</h3><div className="tryon-views">{views.map(([view, label]) =>
        <ImageInput key={view} label={label} asset={items[view]}
          onChange={(asset) => setter((old) => { const next = { ...old }; if (asset) next[view] = asset; else delete next[view]; return next; })}
          onBusy={(value) => setBusyCount((n) => n + (value ? 1 : -1))} />)}</div></section>)}</div>
    <label className="confirmation"><input type="checkbox" checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)} />
      我确认人物各视角是同一个人、同一姿势；服装各视角是同一件衣服</label>
    <button className="generate-button tryon-generate" disabled={!complete || !confirmed || busyCount > 0 || submitting || !caps?.tryon}
      onClick={() => void generate()}>{submitting ? <LoaderCircle className="spin" size={17} /> : <Sparkles size={17} />}生成六视图试穿</button>
    {error && <p className="settings-error" role="alert">{error}</p>}
    {current && <section className="tryon-results"><h3>换装结果 · {Object.keys(current.results).length}/6</h3>
      {current.state === 'failed' && <p role="alert">{current.error}</p>}
      {['running', 'submitting', 'queued'].includes(current.state) && <p>正在处理：{views.find(([view]) => view === current.active_view)?.[1] || '排队中'}。六次生成可能产生费用。</p>}
      <div className="tryon-views">{views.map(([view, label]) => <div className="tryon-result" key={view}>
        {current.results[view] ? <><img src={fileUrl(current.results[view])} alt={`换装后${label}`} /><a href={`${fileUrl(current.results[view])}?download=true`}><Download size={15} /> 保存{label}</a></> : <div className="tryon-placeholder">{label} · 待生成</div>}
      </div>)}</div>
      {current.state === 'ready' && <div className="tryon-next"><p>六张结果已保存到本地。请先检查身份、脸部、体型、服装与各角度一致性；你可以到此结束，也可以继续生成 3D。</p>
        <button className="button" onClick={() => void continue3D()} disabled={submitting || !caps?.geometry}>继续生成 3D 模型 <ArrowRight size={16} /></button>
        {!caps?.geometry && <small>继续建模前需先配置腾讯云混元 3D。</small>}</div>}
    </section>}
  </main>;
}
