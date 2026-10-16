import React, { useCallback, useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { Check, AlertCircle, X, Download } from 'lucide-react';
import { Shell, Modal, Button } from './ui';
import Parser from './Parser';
import Downloads, { Queue } from './Downloads';
import { History, SettingsPage, HelpContent, PlatformSupport } from './OtherPages';
import { api, post, saveFile, fileUrl } from './api';
import './styles.css';

function loadDefaults() {
  const base = { videoFormat: 'mp4', audioFormat: 'mp3', autoSave: true, preferWorker: false };
  try { return { ...base, ...JSON.parse(localStorage.getItem('shiying.preferences.v1') || '{}') }; } catch { return base; }
}

function App() {
  const [page, setPageState] = useState('parse');
  const [mode, setMode] = useState('single');
  const [input, setInput] = useState('');
  const [results, setResults] = useState([]);
  const [tasks, setTasks] = useState([]);
  const [history, setHistory] = useState([]);
  const [health, setHealth] = useState(null);
  const [defaults, setDefaults] = useState(loadDefaults);
  const [toast, setToast] = useState(null);
  const [modal, setModal] = useState(null);
  const autoSave = useRef(new Set());
  const defaultsRef = useRef(defaults);
  const toastTimer = useRef(null);
  const closeModal = useCallback(() => setModal(null), []);
  const notify = useCallback((message, error = false) => {
    clearTimeout(toastTimer.current);
    setToast({ message, error });
    toastTimer.current = setTimeout(() => setToast(null), error ? 8000 : 4500);
  }, []);
  function setPage(value) { setPageState(value); window.scrollTo({ top: 0 }); }
  const refreshHistory = useCallback(() => api('/history').then(data => setHistory(data.results)).catch(() => {}), []);
  useEffect(() => {
    const handler = event => notify(event.detail, true);
    window.addEventListener('shiying:error', handler);
    return () => window.removeEventListener('shiying:error', handler);
  }, [notify]);
  useEffect(() => () => { if (modal?.file?.url?.startsWith('blob:')) URL.revokeObjectURL(modal.file.url); }, [modal]);
  const refreshTasks = useCallback(async () => {
    const response = await api('/tasks');
    setTasks(response.tasks);
    for (const task of response.tasks) {
      if (autoSave.current.has(task.id) && task.status === 'completed') {
        autoSave.current.delete(task.id);
        if (defaultsRef.current.autoSave) saveFile(task.id);
        notify(`“${task.title}”已完成，可在下载管理中保存到设备。`);
      }
      if (autoSave.current.has(task.id) && task.status === 'failed') { autoSave.current.delete(task.id); notify(task.error || '下载失败，请查看下载管理。', true); }
    }
  }, [notify]);
  useEffect(() => {
    let cancelled = false;
    let timer;
    async function poll() {
      try {
        await Promise.all([api('/health').then(data => { if (!cancelled) setHealth(data); }), refreshTasks()]);
      } catch { if (!cancelled) setHealth(null); }
      if (!cancelled) timer = setTimeout(poll, document.hidden ? 5000 : 1200);
    }
    poll(); refreshHistory();
    return () => { cancelled = true; clearTimeout(timer); clearTimeout(toastTimer.current); };
  }, [refreshTasks, refreshHistory]);
  function updateDefaults(value) { setDefaults(value); defaultsRef.current = value; try { localStorage.setItem('shiying.preferences.v1', JSON.stringify(value)); } catch { notify('浏览器不能保存偏好，本次设置仍然有效。'); } }
  async function start(item, options, silent = false) {
    try {
      const task = await post('/tasks', { parsed_id: item.id, ...options });
      if (!options.queued) autoSave.current.add(task.id);
      await refreshTasks();
      if (!silent) notify(options.queued ? '已加入队列，可在下载管理中继续下载。' : '任务已开始，完成后可保存到当前设备。');
    } catch (error) { notify(error.message, true); if (silent) throw error; }
  }
  async function action(id, value) {
    try { await post(`/tasks/${id}/${value}`); if (['resume', 'retry'].includes(value)) autoSave.current.add(id); await refreshTasks(); }
    catch (error) { notify(error.message, true); }
  }
  const taskActions = { action, remove: task => setModal({ type: 'remove', task }), preview: async task => { try { const file = await fileUrl(task.id, true); setModal({ type: 'preview', task, file }); } catch (error) { notify(error.message, true); } } };
  async function confirmRemove() {
    try { await api(`/tasks/${modal.task.id}`, { method: 'DELETE' }); closeModal(); await refreshTasks(); notify('视频任务和文件缓存已删除。'); }
    catch (error) { notify(error.message, true); }
  }
  async function clearHistory() {
    try { await api('/history', { method: 'DELETE' }); setHistory([]); closeModal(); notify('解析记录已清空。'); }
    catch (error) { notify(error.message, true); }
  }
  function useItem(item) { setInput(item.url); setResults([]); setMode('single'); setPage('parse'); notify('链接已填入，点击“解析链接”获取最新信息。'); }
  return <><Shell page={page} setPage={setPage} activeCount={tasks.filter(task => ['queued', 'downloading', 'processing'].includes(task.status)).length} health={health} help={() => setModal({ type: 'help' })}>
    {!health ? <div className="service-banner" role="status"><AlertCircle size={18}/>正在连接下载服务。如果长时间未连接，请按启动说明运行服务。</div> : null}
    {page === 'parse' ? <Parser results={results} setResults={setResults} input={input} setInput={setInput} mode={mode} setMode={setMode} start={start} defaults={{ ...defaults, preferWorker: Boolean(defaults.preferWorker && health?.worker_configured) }} notify={notify} morePlatforms={() => setModal({ type: 'platforms' })} parsedDone={refreshHistory}><Queue tasks={tasks} open={() => setPage('downloads')} {...taskActions}/></Parser> : null}
    {page === 'downloads' ? <Downloads tasks={tasks} health={health} newDownload={() => setPage('parse')} {...taskActions}/> : null}
    {page === 'history' ? <History history={history} useItem={useItem} clear={() => setModal({ type: 'history' })}/> : null}
    {page === 'settings' ? <SettingsPage health={health} defaults={defaults} updateDefaults={updateDefaults}/> : null}
  </Shell>{toast ? <div className={`toast ${toast.error ? 'error' : ''}`} role={toast.error ? 'alert' : 'status'}>{toast.error ? <AlertCircle size={19}/> : <Check size={19}/>}<span>{toast.message}</span><button onClick={() => setToast(null)} aria-label="关闭提示"><X size={17}/></button></div> : null}
  {modal ? <Modal title={modal.type === 'platforms' ? '国内外平台验证' : modal.type === 'help' ? '使用帮助' : modal.type === 'preview' ? '播放预览' : modal.type === 'history' ? '清空解析记录' : '删除视频'} close={closeModal}>{modal.type === 'platforms' ? <PlatformSupport/> : modal.type === 'help' ? <HelpContent cloud={health?.mode === 'cloud'}/> : modal.type === 'preview' ? <div className="preview-content"><p>{modal.task.title}</p>{modal.task.kind === 'audio' ? <audio src={modal.file?.url} controls autoPlay/> : <video src={modal.file?.url} controls autoPlay/>}<Button variant="primary" onClick={() => saveFile(modal.task.id)}><Download size={18}/>保存到设备</Button></div> : <><p className="confirm-copy">{modal.type === 'history' ? '清空所有解析记录？下载任务和已保存的文件不受影响。' : `删除“${modal.task.title}”的下载任务和文件缓存？已经保存到设备的文件不受影响。`}</p><div className="modal-actions"><Button onClick={closeModal}>取消</Button><Button variant="primary" onClick={modal.type === 'history' ? clearHistory : confirmRemove}>确认{modal.type === 'history' ? '清空' : '删除'}</Button></div></>}</Modal> : null}</>;
}

createRoot(document.getElementById('root')).render(<App/>);
