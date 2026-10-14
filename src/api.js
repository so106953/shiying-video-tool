import { cloudApi, cloudFile, cloudTask, rememberParsed } from './cloud';
let mode;
let modePromise;
async function ensureMode() {
  if (mode !== undefined) return mode;
  if (!modePromise) modePromise = fetch('/api/health').then(res => res.json()).then(data => { mode = data.mode === 'cloud'; return mode; }).catch(error => { modePromise = null; throw error; });
  return modePromise;
}
export async function api(path, options = {}) {
  if (path !== '/health') {
    await ensureMode();
    if (mode && (path.startsWith('/tasks') || path === '/history')) return cloudApi(path, options);
  }
  const response = await fetch(`/api${path}`, {
    ...options,
    headers: { 'Content-Type': 'application/json', ...options.headers },
  });
  let data;
  try { data = await response.json(); } catch { throw new Error('服务响应异常，请确认下载服务已启动。'); }
  if (!response.ok) {
    const detail = typeof data.detail === 'string' ? data.detail : '请求失败，请检查输入后重试。';
    throw new Error(detail);
  }
  if (path === '/health') mode = data.mode === 'cloud';
  if (path === '/parse' && mode) rememberParsed(data.results);
  return data;
}
export const post = (path, body = {}) => api(path, { method: 'POST', body: JSON.stringify(body) });
export function bytes(value) {
  if (!value) return '—';
  if (value < 1024) return `${value} B`;
  const units = ['KB', 'MB', 'GB'];
  let number = value / 1024, unit = 0;
  while (number >= 1024 && unit < 2) { number /= 1024; unit++; }
  return `${number.toFixed(1)} ${units[unit]}`;
}
export function duration(seconds) {
  if (!seconds) return '';
  const total = Math.floor(seconds);
  return `${Math.floor(total / 60).toString().padStart(2, '0')}:${(total % 60).toString().padStart(2, '0')}`;
}
export function linksFromText(text) {
  return [...new Set((text.match(/https?:\/\/[^\s<>"“”]+/gi) || []).map(url => url.replace(/[，。；！、）)\]}]+$/, '')))];
}
export async function fileUrl(id, preview = false) {
  if (cloudTask(id)) return cloudFile(id);
  return { url: `/api/tasks/${id}/file${preview ? '?preview=true' : ''}`, filename: '' };
}
export async function saveFile(id) {
  let file;
  try { file = await fileUrl(id); } catch (error) { window.dispatchEvent(new CustomEvent('shiying:error', { detail: error.message })); return; }
  const link = document.createElement('a');
  link.href = file.url;
  link.download = file.filename;
  document.body.append(link);
  link.click();
  link.remove();
  if (file.url.startsWith('blob:')) setTimeout(() => URL.revokeObjectURL(file.url), 60000);
}
