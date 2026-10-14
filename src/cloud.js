// Cloud queues and media stay on this device. The Vercel API holds no mutable state.
const TASKS = 'shiying.cloud.tasks.v1';
const HISTORY = 'shiying.cloud.history.v1';
const controllers = new Map();
let dbPromise;
let pumping = false;
function read(key) { try { return JSON.parse(localStorage.getItem(key) || '[]'); } catch { return []; } }
function write(key, value) { localStorage.setItem(key, JSON.stringify(value)); }
function update(id, change) { const list = read(TASKS); const task = list.find(item => item.id === id); if (!task) return; Object.assign(task, change); write(TASKS, list); return task; }
function database() {
  if (!dbPromise) dbPromise = new Promise((resolve, reject) => {
    const request = indexedDB.open('shiying.media.v1', 1);
    request.onupgradeneeded = () => request.result.createObjectStore('chunks', { keyPath: 'key' });
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(new Error('浏览器不允许缓存文件，请退出隐私模式后重试。'));
  });
  return dbPromise;
}
async function chunkAction(mode, callback) {
  const db = await database();
  return new Promise((resolve, reject) => {
    const transaction = db.transaction('chunks', mode);
    const request = callback(transaction.objectStore('chunks'));
    let result;
    request.onsuccess = () => { result = request.result; };
    transaction.oncomplete = () => resolve(result);
    transaction.onerror = () => reject(new Error('设备存储空间不足，或浏览器无法保存缓存。'));
    transaction.onabort = () => reject(new Error('文件缓存被中断，请重试。'));
  });
}
const chunksFor = id => chunkAction('readonly', store => store.getAll(IDBKeyRange.bound(`${id}:`, `${id}:~`))).then(rows => rows.sort((a, b) => a.offset - b.offset));
async function deleteChunks(id) {
  const rows = await chunksFor(id);
  await Promise.all(rows.map(row => chunkAction('readwrite', store => store.delete(row.key))));
}
const initialized = new Set();
function initialize() {
  if (initialized.has(TASKS)) return;
  initialized.add(TASKS);
  const list = read(TASKS).map(task => ['downloading', 'processing', 'pausing', 'cancelling'].includes(task.status) ? { ...task, status: 'paused', speed: 0, error: '页面已重载，点击继续可恢复下载。' } : task);
  write(TASKS, list);
}
async function run(id) {
  const controller = new AbortController();
  controllers.set(id, controller);
  update(id, { status: 'downloading', error: null });
  try {
    const chunks = await chunksFor(id);
    let offset = 0;
    for (const piece of chunks) { if (piece.offset !== offset) throw new Error('文件缓存不完整，请移除任务后重新下载。'); offset += piece.blob.size; }
    let ended = false;
    while (!ended) {
      const task = read(TASKS).find(item => item.id === id);
      if (!task || task.status !== 'downloading') break;
      const before = performance.now();
      const response = await fetch('/api/chunk', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ticket: task.ticket, offset }), signal: controller.signal });
      if (!response.ok) { let error; try { error = await response.json(); } catch { /* platform timeout */ } throw new Error(error?.detail || `下载服务暂时不可用 (${response.status})，请重试。`); }
      const blob = await response.blob();
      if (controller.signal.aborted) throw new DOMException('Aborted', 'AbortError');
      if (blob.size) await chunkAction('readwrite', store => store.put({ key: `${id}:${String(offset).padStart(12, '0')}`, offset, blob }));
      offset += blob.size;
      const total = Number(response.headers.get('X-Media-Total')) || task.total || 0;
      ended = response.headers.get('X-Media-End') === '1';
      if (!blob.size && !ended) throw new Error('媒体服务器没有返回文件内容。');
      const speed = blob.size / Math.max(.1, (performance.now() - before) / 1000);
      update(id, { downloaded: offset, total, speed, progress: total ? Math.min(99, offset / total * 100) : 0, eta: total ? Math.ceil((total - offset) / speed) : null });
    }
    if (ended && !controller.signal.aborted) update(id, { status: 'completed', progress: 100, downloaded: offset, total: offset, speed: 0, eta: null, completed: Date.now() / 1000 });
  } catch (error) {
    const task = read(TASKS).find(item => item.id === id);
    if (task && !['paused', 'cancelled'].includes(task.status)) update(id, { status: 'failed', error: error.message, speed: 0, eta: null });
  } finally { controllers.delete(id); pump(); }
}
function pump() {
  if (pumping) return;
  pumping = true;
  initialize();
  const pending = read(TASKS).filter(task => task.status === 'queued' && !controllers.has(task.id)).reverse();
  for (const task of pending.slice(0, Math.max(0, 2 - controllers.size))) run(task.id);
  pumping = false;
}
export function rememberParsed(results) {
  const successful = results.filter(item => item.status === 'success');
  write(HISTORY, [...successful, ...read(HISTORY)].slice(0, 100));
}
export async function cloudApi(path, options = {}) {
  initialize();
  const method = options.method || 'GET';
  if (path === '/history') {
    if (method === 'DELETE') { write(HISTORY, []); return { ok: true }; }
    return { results: read(HISTORY) };
  }
  if (path === '/tasks' && method === 'GET') { pump(); return { tasks: read(TASKS) }; }
  if (path === '/tasks' && method === 'POST') {
    const body = JSON.parse(options.body);
    const parsed = read(HISTORY).find(item => item.id === body.parsed_id);
    if (!parsed) throw new Error('解析结果已过期，请重新解析。');
    const source = parsed.options.find(item => item.kind === body.kind && item.format === body.format && (body.kind === 'audio' || item.height === (body.height || null)));
    if (!source) throw new Error('当前画质没有这个格式，请选择实际可用格式。');
    if (read(TASKS).filter(item => ['queued', 'downloading'].includes(item.status)).length >= 20) throw new Error('队列已满，请先完成当前下载。');
    await database();
    const task = { id: crypto.randomUUID().replaceAll('-', ''), parsed_id: parsed.id, url: parsed.url, title: parsed.title, thumbnail: parsed.thumbnail, platform: parsed.platform, kind: body.kind, format: body.format, height: body.height, ticket: source.ticket, cloud: true, filename: `${parsed.title.replace(/[\\/:*?"<>|]/g, '_').slice(0, 120)}.${source.format}`, status: body.queued ? 'paused' : 'queued', created: Date.now() / 1000, progress: 0, downloaded: 0, total: source.size || 0, speed: 0, eta: null, error: null };
    write(TASKS, [task, ...read(TASKS)]);
    pump();
    return task;
  }
  const match = path.match(/^\/tasks\/([^/]+)(?:\/(pause|resume|retry|cancel))?$/);
  if (match) {
    const [, id, action] = match;
    const task = read(TASKS).find(item => item.id === id);
    if (!task) throw new Error('下载任务不存在。');
    if (method === 'DELETE') {
      if (controllers.has(id) || task.status === 'queued') throw new Error('请先暂停正在下载的任务。');
      await deleteChunks(id); write(TASKS, read(TASKS).filter(item => item.id !== id)); return { ok: true };
    }
    if (action === 'pause' || action === 'cancel') {
      update(id, { status: action === 'pause' ? 'paused' : 'cancelled', speed: 0, eta: null });
      controllers.get(id)?.abort();
    } else if (action === 'resume' || action === 'retry') {
      if (controllers.has(id)) throw new Error('正在结束上一段传输，请稍后继续。');
      update(id, { status: 'queued', error: null }); pump();
    }
    return read(TASKS).find(item => item.id === id);
  }
  throw new Error('当前云端版本不支持此操作。');
}
export function cloudTask(id) { return read(TASKS).find(item => item.id === id); }
export async function cloudFile(id) {
  const task = cloudTask(id);
  if (!task || task.status !== 'completed') throw new Error('文件尚未完成。');
  const chunks = await chunksFor(id);
  if (!chunks.length || chunks.reduce((n, row) => n + row.blob.size, 0) !== task.total) throw new Error('设备缓存已被浏览器清理，请重新下载。');
  const type = task.kind === 'audio' ? (task.format === 'mp3' ? 'audio/mpeg' : task.format === 'm4a' ? 'audio/mp4' : 'audio/ogg') : task.format === 'webm' ? 'video/webm' : 'video/mp4';
  return { url: URL.createObjectURL(new Blob(chunks.map(row => row.blob), { type })), filename: task.filename };
}
