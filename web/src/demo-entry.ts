import catalog from './demo-data.json';

// Demo-only entry: all API traffic is resolved locally; production entries never import this module.
const nativeFetch = globalThis.fetch.bind(globalThis);
globalThis.fetch = async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
  const requestUrl = input instanceof Request ? input.url : input.toString();
  const url = new URL(requestUrl, location.href);
  const method = (init?.method ?? (input instanceof Request ? input.method : 'GET')).toUpperCase();
  if (url.origin !== location.origin) return Response.json({ detail: '演示页面不连接外部服务。' }, { status: 403 });
  const path = url.pathname;
  if (path.includes('/api/') || path.includes('/public/')) {
    if (method !== 'GET' && method !== 'HEAD') return Response.json({ detail: '演示页面未启用账号和上传。' }, { status: 403 });
    if (path.endsWith('/api/v1/catalog')) return Response.json(catalog);
    if (path.endsWith('/api/v1/auth/me')) return Response.json({ authenticated: false, localEnabled: false, registrationEnabled: false, oidcEnabled: false });
    if (path.endsWith('/api/v1/library/wallpapers')) return Response.json({ wallpapers: [] });
    if (path.endsWith('/public/index-status.json')) return Response.json({ state: 'ready' });
    if (path.endsWith('/public/settings.json')) return Response.json({});
    return Response.json({ detail: '演示中未启用此功能。' }, { status: 404 });
  }
  return nativeFetch(input, init);
};
const note = document.createElement('aside');
note.textContent = 'WALLPAPER WALL / DEMO · 示例图库';
note.setAttribute('aria-label', '演示模式，所有图片均为原创合成示例');
note.style.cssText = 'position:fixed;z-index:999;top:18px;left:50%;transform:translateX(-50%);padding:10px 18px;border:1px solid #ffffff24;border-radius:99px;background:#101a29d9;backdrop-filter:blur(16px);color:#e8f1ff;font:11px ui-monospace,monospace;letter-spacing:1.2px;pointer-events:none;white-space:nowrap';
document.body.append(note);
document.addEventListener('click', (event) => {
  const target = event.target instanceof Element ? event.target.closest('.viewer-wallpaper, a[href^="wallpaperwall:"], a[href^="intent:"]') : null;
  if (!target) return;
  event.preventDefault(); event.stopImmediatePropagation();
  void import('./toast').then(({ showWallToast }) => showWallToast('演示中不调用本机壁纸助手。'));
}, true);
if (document.querySelector('#wall')) void import('./main');
else void import('./detail');
