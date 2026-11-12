import { api, getSession, type SessionState } from './api';
import { confirmDialog } from './modal';

const LOCAL_KEY = 'wallpaper-wall:favorites:v1';

function localIds(): Set<string> {
  try {
    const value: unknown = JSON.parse(localStorage.getItem(LOCAL_KEY) ?? '[]');
    return new Set(Array.isArray(value) ? value.filter((id): id is string => typeof id === 'string' && id.length > 0 && id.length <= 256).slice(0, 5_000) : []);
  } catch {
    return new Set();
  }
}

export class FavoritesStore {
  private ids = new Set<string>();
  private session: SessionState = { authenticated: false, localEnabled: false, registrationEnabled: false, oidcEnabled: false };
  private readonly listeners = new Set<() => void>();
  private readonly pending = new Map<string, Promise<boolean>>();

  get authenticated(): boolean {
    return this.session.authenticated;
  }

  get accountName(): string | undefined {
    return this.session.user?.display_name;
  }

  get avatarUrl(): string | undefined {
    // http(s) portraits and inline `data:image/*` avatars (authentik serves its
    // default initials avatar as `data:image/svg+xml`) are both safe in an <img>.
    const url = this.session.user?.avatar_url;
    return url && /^(https?:\/\/|data:image\/)/i.test(url) ? url : undefined;
  }

  get role(): 'user' | 'admin' | undefined {
    return this.session.user?.role;
  }

  get oidcEnabled(): boolean {
    return this.session.oidcEnabled;
  }

  get localEnabled(): boolean {
    return this.session.localEnabled;
  }

  get registrationEnabled(): boolean {
    return this.session.registrationEnabled;
  }

  get inviteRequired(): boolean {
    return Boolean(this.session.inviteRequired);
  }

  get isLocalAccount(): boolean {
    return Boolean(this.session.user?.local);
  }

  get csrfToken(): string | undefined {
    return this.session.csrfToken;
  }

  async initialize(): Promise<void> {
    const guestIds = localIds();
    this.session = await getSession();
    if (this.session.authenticated) {
      const remote = await api<{ wallpaperIds: string[] }>('api/v1/favorites');
      this.ids = new Set(remote.wallpaperIds);
      // Import is explicit: the user can retain a browser-only list instead
      // of silently sending it to their account at first login.
      if (
        guestIds.size &&
        (await confirmDialog({
          title: '同步本地收藏',
          message: `是否将此浏览器中的 ${guestIds.size} 个喜欢同步到当前账号？`,
          confirmLabel: '同步',
          cancelLabel: '暂不',
        }))
      ) {
        const merged = await api<{ wallpaperIds: string[] }>(
          'api/v1/favorites/merge',
          { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ wallpaper_ids: [...guestIds] }) },
          this.session.csrfToken,
        );
        this.ids = new Set(merged.wallpaperIds);
        localStorage.removeItem(LOCAL_KEY);
      }
    } else {
      this.ids = guestIds;
    }
    this.emit();
  }

  has(id: string): boolean {
    return this.ids.has(id);
  }

  values(): ReadonlySet<string> {
    return this.ids;
  }

  subscribe(listener: () => void): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  toggle(id: string): Promise<boolean> {
    const previous = this.pending.get(id) ?? Promise.resolve(this.ids.has(id));
    const operation = previous.catch(() => this.ids.has(id)).then(() => this.toggleNow(id));
    this.pending.set(id, operation);
    operation.then(
      () => { if (this.pending.get(id) === operation) this.pending.delete(id); },
      () => { if (this.pending.get(id) === operation) this.pending.delete(id); },
    );
    return operation;
  }

  private async toggleNow(id: string): Promise<boolean> {
    const next = !this.ids.has(id);
    // Optimistic UI keeps virtualised cards responsive; errors restore truth.
    if (next) this.ids.add(id);
    else this.ids.delete(id);
    this.emit();
    try {
      if (this.session.authenticated) {
        await api<void>(`api/v1/favorites/${encodeURIComponent(id)}`, { method: next ? 'PUT' : 'DELETE' }, this.session.csrfToken);
      } else {
        localStorage.setItem(LOCAL_KEY, JSON.stringify([...this.ids]));
      }
      return next;
    } catch (error) {
      if (next) this.ids.delete(id);
      else this.ids.add(id);
      this.emit();
      throw error;
    }
  }

  private emit(): void {
    this.listeners.forEach((listener) => listener());
  }
}
