import { useState } from 'react';
import { ArrowRight, Clipboard, Download, Plus, RotateCw, Link2, Play, Video, ChevronRight } from 'lucide-react';
import { Button, PageHeading, Status, Thumb, Empty } from './ui';
import { bytes, duration, linksFromText, post } from './api';

const platformLabels = [['B', '哔哩哔哩', 'bilibili'], ['♪', '抖音', 'douyin'], ['书', '小红书', 'redbook'], ['▶', 'YouTube', 'youtube'], ['♪', 'TikTok', 'douyin']];
export function Platforms({ onMore }) { return <div className="platform-row"><span className="muted platform-caption">平台适配</span>{platformLabels.map(([mark, name, className]) => <span className="platform" key={name}><i className={className}>{mark}</i>{name}</span>)}<button className="text-button" onClick={onMore}>••• <span>更多平台</span></button></div>; }

export function Result({ item, start, defaults, notify }) {
  const initialKind = item.cloud && !item.options.some(option => option.kind === 'video') ? 'audio' : 'video';
  const initialHeight = item.recommended_height || item.heights?.[0] || '';
  const [kind, setKind] = useState(initialKind);
  const [height, setHeight] = useState(initialHeight);
  const [format, setFormat] = useState(item.cloud ? item.options.find(option => option.kind === initialKind && (initialKind === 'audio' || option.height === (initialHeight || null)))?.format || 'mp4' : defaults.videoFormat || 'mp4');
  const [busy, setBusy] = useState(false);
  const [playing, setPlaying] = useState(false);
  const previewSource = item.cloud ? `/api/media?ticket=${encodeURIComponent(item.options.find(option => option.kind === 'video')?.ticket || '')}` : item.url;
  async function download(queued) {
    setBusy(true);
    try { await start(item, { kind, height: height ? Number(height) : null, format, queued }); }
    finally { setBusy(false); }
  }
  function changeKind(value) { setKind(value); setFormat(item.cloud ? item.options.find(option => option.kind === value && (value === 'audio' || option.height === (Number(height) || null)))?.format || 'mp4' : value === 'audio' ? defaults.audioFormat || 'mp3' : defaults.videoFormat || 'mp4'); }
  function changeHeight(value) { setHeight(value); if (item.cloud) setFormat(item.options.find(option => option.kind === kind && option.height === (Number(value) || null))?.format || format); }
  const availableFormats = item.cloud ? [...new Set(item.options.filter(option => option.kind === kind && (kind === 'audio' || option.height === (Number(height) || null))).map(option => option.format))] : kind === 'audio' ? ['mp3', 'm4a'] : ['mp4', 'mkv'];
  return <section className="panel result-panel"><div className="section-heading"><h2>解析结果</h2><Status good>解析完成</Status></div><div className="result-layout">
    <div className="result-media">{item.direct && initialKind === 'video' && item.ext !== 'mp3' ? <video key={item.url} src={previewSource} preload="metadata" controls={playing} onClick={() => setPlaying(true)} aria-label="视频预览"/> : <Thumb src={item.thumbnail} className="large"/>}{!playing && item.direct && initialKind === 'video' ? <button className="play-button" onClick={event => { setPlaying(true); const video = event.currentTarget.parentElement.querySelector('video'); video?.play().catch(() => notify('请点击视频播放控件开始播放')); }} aria-label="播放视频"><Play size={24} fill="currentColor"/></button> : null}{duration(item.duration) ? <span className="duration">{duration(item.duration)}</span> : null}</div>
    <div className="result-details"><h3>{item.title}</h3><p className="creator">{item.uploader} <span>·</span> {item.platform}</p><div className="segmented" aria-label="媒体类型"><button disabled={item.cloud && !item.options.some(option => option.kind === 'video')} className={kind === 'video' ? 'selected' : ''} onClick={() => changeKind('video')}>视频</button><button disabled={item.cloud && !item.options.some(option => option.kind === 'audio')} className={kind === 'audio' ? 'selected' : ''} onClick={() => changeKind('audio')}>仅音频</button></div><div className="result-options"><label>清晰度<select value={height} onChange={event => changeHeight(event.target.value)} disabled={kind === 'audio'}>{item.heights?.length ? item.heights.map(value => <option key={value} value={value}>{value >= 2160 ? '4K 超清' : `${value}P${value >= 1080 ? ' 高清' : ''}`}</option>) : <option value="">原始画质</option>}</select></label><label>格式<select value={format} onChange={event => setFormat(event.target.value)}>{availableFormats.map(value => <option key={value} value={value}>{value.toUpperCase()}</option>)}</select></label><div className="download-actions"><Button variant="primary" disabled={busy} onClick={() => download(false)}><Download size={18}/>{busy ? '正在添加…' : '下载到本地'}</Button><Button variant="outline" disabled={busy} onClick={() => download(true)}><Plus size={18}/>加入队列</Button></div></div><p className="size-note">{item.size ? `参考大小：${bytes(item.size)} · 实际大小以文件为准` : '文件大小将在下载时显示'}{item.cloud ? ' · 云端仅提供无需转码的格式' : ''}</p></div>
  </div></section>;
}

function BatchResults({ results, update, start, defaults, notify }) {
  const successful = results.filter(item => item.status === 'success');
  const [selected, setSelected] = useState(() => new Set(successful.map(item => item.id)));
  const [heights, setHeights] = useState({});
  const [busy, setBusy] = useState(false);
  const [retrying, setRetrying] = useState(new Set());
  const [format, setFormat] = useState(defaults.videoFormat || 'mp4');
  function toggle(id) { setSelected(previous => { const next = new Set(previous); next.has(id) ? next.delete(id) : next.add(id); return next; }); }
  async function retry(item) {
    setRetrying(previous => new Set(previous).add(item.id));
    try {
      const data = await post('/parse', { urls: [item.url] });
      const replacement = data.results[0];
      update(old => old.map(row => row.id === item.id ? replacement : row));
      if (replacement.status === 'success') setSelected(old => new Set(old).add(replacement.id));
    } catch (error) { notify(error.message, true); }
    finally { setRetrying(old => { const next = new Set(old); next.delete(item.id); return next; }); }
  }
  async function download(queued) {
    setBusy(true);
    try {
      for (const item of successful.filter(row => selected.has(row.id))) {
        const height = heights[item.id] || item.recommended_height || item.heights?.[0] || null;
        const option = item.cloud ? item.options.find(value => value.kind === 'video' && value.height === height && value.format === format) || item.options.find(value => value.kind === 'video' && value.height === height) || item.options[0] : null;
        await start(item, { kind: option?.kind || 'video', height: option?.height || height, format: option?.format || format, queued }, true);
      }
      notify(queued ? '已加入队列，可在下载管理中开始任务' : '所选视频已开始下载');
    } catch (error) { notify(error.message, true); } finally { setBusy(false); }
  }
  const picked = successful.filter(row => selected.has(row.id));
  return <><section className="panel batch-panel"><div className="section-heading"><h2>解析结果</h2><span className="muted">{successful.length} 条成功，{results.length - successful.length} 条待重试</span></div><div className="batch-toolbar"><label className="check-label"><input type="checkbox" checked={successful.length > 0 && picked.length === successful.length} onChange={() => setSelected(picked.length === successful.length ? new Set() : new Set(successful.map(item => item.id)))}/>已选择 {picked.length} 项</label><Button variant="outline" disabled={retrying.size > 0 || successful.length === results.length} onClick={() => results.filter(item => item.status === 'error').forEach(retry)}><RotateCw size={15}/>重试失败项</Button></div><div className="batch-table"><div className="batch-header"><span/><span>视频</span><span>平台</span><span>清晰度</span><span>状态 / 操作</span></div>{results.map(item => <div className="batch-row" key={item.id}><input aria-label={`选择 ${item.title || item.url}`} type="checkbox" disabled={item.status !== 'success'} checked={selected.has(item.id)} onChange={() => toggle(item.id)}/><div className="batch-video"><Thumb src={item.thumbnail}/><div><strong>{item.title || '视频链接'}</strong><small>{item.status === 'success' ? [duration(item.duration), 'MP4', item.size ? bytes(item.size) : '大小待确认'].filter(Boolean).join(' · ') : item.url}</small></div></div><span className="batch-platform">{item.platform || '—'}</span><select aria-label={`${item.title || '视频'}清晰度`} value={heights[item.id] || item.recommended_height || item.heights?.[0] || ''} disabled={item.status !== 'success'} onChange={event => setHeights(old => ({ ...old, [item.id]: Number(event.target.value) }))}>{item.heights?.length ? item.heights.map(value => <option key={value} value={value}>{value}P</option>) : <option value="">原始画质</option>}</select><div className="batch-status">{item.status === 'success' ? <Status good>解析成功</Status> : <><Status>解析失败</Status><small>{item.error}</small><Button onClick={() => retry(item)} disabled={retrying.has(item.id)}><RotateCw size={14}/>{retrying.has(item.id) ? '重试中…' : '重试'}</Button></>}</div></div>)}</div></section><div className="panel batch-settings"><label>默认格式<select value={format} onChange={event => setFormat(event.target.value)}><option value="mp4">MP4</option><option value="mkv">MKV</option></select></label><span>保存位置 <strong>浏览器默认下载目录</strong></span></div><div className="panel batch-actions"><span>已选择 {picked.length} 个视频</span><div><Button variant="outline" disabled={!picked.length || busy} onClick={() => download(true)}><Plus size={18}/>加入下载队列</Button><Button variant="primary" disabled={!picked.length || busy} onClick={() => download(false)}><Download size={18}/>下载所选 ({picked.length})</Button></div></div></>;
}

export default function Parser({ results, setResults, input, setInput, mode, setMode, start, defaults, notify, morePlatforms, children, parsedDone }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  async function parse() {
    const urls = linksFromText(input);
    if (!urls.length) { setError('请先粘贴有效的视频链接，也可以粘贴包含链接的分享文字。'); return; }
    if (mode === 'single' && urls.length > 1) { setError('检测到多个链接，请切换到批量解析。'); return; }
    if (urls.length > 20) { setError('每批最多解析 20 个链接，请分批处理。'); return; }
    setBusy(true); setError(''); setResults([]);
    try {
      const response = await post('/parse', { urls });
      setResults(response.results);
      parsedDone();
      if (mode === 'single' && response.results[0].status === 'error') setError(response.results[0].error);
    } catch (err) { setError(err.message); }
    finally { setBusy(false); }
  }
  async function paste() {
    try { setInput(await navigator.clipboard.readText()); setError(''); }
    catch { notify('浏览器未允许读取剪贴板，请长按输入框或使用 Ctrl / ⌘ + V 粘贴。', true); }
  }
  const first = results.find(item => item.status === 'success');
  return <><PageHeading title={mode === 'single' ? '让每一个精彩，留在本地。' : '一次粘贴，批量保存。'} subtitle={mode === 'single' ? '粘贴视频链接，选择清晰度，轻松保存到你的设备。' : '多个平台的链接，也能在同一个地方处理。'}/><section className="panel parse-panel"><div className="tabs" role="tablist" aria-label="解析方式">{[['single', '单个链接'], ['batch', '批量解析']].map(([value, label]) => <button key={value} role="tab" aria-selected={mode === value} className={mode === value ? 'active' : ''} onClick={() => { setMode(value); setError(''); }} disabled={busy}>{label}</button>)}</div><div className="link-input"><textarea aria-label="视频链接" value={input} onChange={event => setInput(event.target.value)} placeholder={mode === 'single' ? '粘贴视频链接，或包含链接的分享文字' : '每行一个视频链接，最多支持 20 条'} disabled={busy}/><Button className="paste-button" onClick={paste} disabled={busy}><Clipboard size={17}/>粘贴</Button></div><div className="parse-controls"><span className="muted">{mode === 'batch' ? `每行一个链接 · 已识别 ${linksFromText(input).length} 条链接` : '自动识别平台 · 支持视频与音频'}{input && mode === 'batch' ? <button className="text-button" onClick={() => { setInput(''); setError(''); }}>清空</button> : null}</span><Button variant="primary" onClick={parse} disabled={busy}>{busy ? <span className="spinner"/> : null}{busy ? '正在解析…' : mode === 'batch' ? '解析全部' : '解析链接'}{!busy ? <ArrowRight size={18}/> : null}</Button></div>{error ? <div className="inline-error" role="alert"><Link2 size={17}/>{error}</div> : null}{busy ? <p className="loading-note" role="status">正在获取真实视频信息，平台响应可能需要一点时间。</p> : null}<Platforms onMore={morePlatforms}/></section>
  {mode === 'single' && first ? <Result key={first.id} item={first} start={start} defaults={defaults} notify={notify}/> : null}{mode === 'batch' && results.length ? <BatchResults key={results.map(item => item.id).join(',')} results={results} update={setResults} start={start} defaults={defaults} notify={notify}/> : null}{!results.length && !busy ? <section className="panel"><Empty title="精彩，从一个链接开始" subtitle="解析后，这里会显示视频预览、可用画质和下载选项。" icon={Video}/></section> : null}{children}</>;
}
