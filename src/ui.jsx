import { useEffect, useRef } from 'react';
import { Link2, Download, Clock3, Settings, CircleHelp, ChevronRight, X, Video, Music2, Check, AlertCircle } from 'lucide-react';

export const NAV = [
  { id: 'parse', label: '链接解析', icon: Link2 },
  { id: 'downloads', label: '下载管理', icon: Download },
  { id: 'history', label: '解析记录', icon: Clock3 },
  { id: 'settings', label: '设置', icon: Settings },
];

export function Brand() {
  return <div className="brand"><svg width="40" height="40" viewBox="0 0 40 40" fill="none" aria-hidden="true"><path d="M23 16v-3a8 8 0 0 0-16 0v8a8 8 0 0 0 8 8h4M17 24v3a8 8 0 0 0 16 0v-8a8 8 0 0 0-8-8h-4" stroke="currentColor" strokeWidth="3.7" strokeLinecap="round"/></svg><div><strong>拾影</strong><small>视频解析与下载</small></div></div>;
}

export function Shell({ page, setPage, activeCount, health, children, help }) {
  const title = NAV.find(item => item.id === page)?.label;
  return <div className="app-shell">
    <aside className="sidebar"><Brand/><nav aria-label="主导航">{NAV.slice(0, 3).map(({ id, label, icon: Icon }) => <button key={id} className={`nav-item ${page === id ? 'active' : ''}`} onClick={() => setPage(id)} aria-current={page === id ? 'page' : undefined}><Icon size={21}/><span>{label}</span>{id === 'downloads' && activeCount > 0 ? <span className="count">{activeCount}</span> : null}</button>)}</nav><div className="sidebar-bottom"><button className={`nav-item ${page === 'settings' ? 'active' : ''}`} onClick={() => setPage('settings')}><Settings size={21}/>设置</button><small>v1.0 · 本地下载工具</small></div></aside>
    <div className="main-shell"><header className="topbar"><div className="mobile-brand"><Brand/></div><div className="breadcrumb">工作台 <ChevronRight size={14}/> <strong>{title}</strong></div><div className="top-actions"><span className={`connection ${health ? 'online' : ''}`}><i/>{health ? '服务已连接' : '连接中'}</span><button className="help-button" onClick={help} aria-label="使用帮助"><CircleHelp size={20}/><span>使用帮助</span></button></div></header><main>{children}<footer className="page-footer">拾影 · 让精彩留在本地</footer></main></div>
    <nav className="mobile-nav" aria-label="手机主导航">{NAV.map(({ id, label, icon: Icon }) => <button key={id} onClick={() => setPage(id)} className={page === id ? 'active' : ''} aria-current={page === id ? 'page' : undefined}><Icon size={22}/><span>{label}</span></button>)}</nav>
  </div>;
}

export function PageHeading({ title, subtitle, children }) { return <div className="page-heading"><div><h1>{title === '让每一个精彩，留在本地。' ? <><span>让每一个精彩，</span><span className="headline-second">留在本地。</span></> : title}</h1><p>{subtitle}</p></div>{children}</div>; }
export function Button({ children, variant = 'default', className = '', ...props }) { return <button className={`button ${variant} ${className}`} {...props}>{children}</button>; }
export function Empty({ title, subtitle, icon: Icon = Video, children }) { return <div className="empty-state"><div className="empty-icon"><Icon size={28} strokeWidth={1.6}/></div><h3>{title}</h3><p>{subtitle}</p>{children}</div>; }
export function Status({ good, children }) { return <span className={`status ${good ? 'success' : 'warning'}`}>{good ? <Check size={14}/> : <AlertCircle size={14}/>} {children}</span>; }
export function Thumb({ src, audio = false, className = '' }) { const Icon = audio ? Music2 : Video; return <div className={`thumb ${className}`}>{src ? <img src={src} loading="lazy" alt="视频封面" onError={event => { event.currentTarget.style.display = 'none'; }}/> : <Icon size={24} strokeWidth={1.5}/>}</div>; }

export function Modal({ title, children, close }) {
  const ref = useRef(null);
  useEffect(() => {
    const before = document.activeElement;
    ref.current?.focus();
    const old = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    function keyboard(event) {
      if (event.key === 'Escape') close();
      if (event.key === 'Tab') {
        const elements = ref.current.querySelectorAll('button,a,input,select,textarea,[tabindex="0"]');
        const first = elements[0], last = elements[elements.length - 1];
        if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
        if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
      }
    }
    document.addEventListener('keydown', keyboard);
    return () => { document.body.style.overflow = old; document.removeEventListener('keydown', keyboard); before?.focus(); };
  }, [close]);
  return <div className="modal-backdrop" onClick={event => { if (event.target === event.currentTarget) close(); }}><section className="modal" role="dialog" aria-modal="true" aria-labelledby="modal-title" tabIndex={-1} ref={ref}><div className="modal-heading"><h2 id="modal-title">{title}</h2><button className="icon-button" onClick={close} aria-label="关闭"><X size={21}/></button></div>{children}</section></div>;
}
