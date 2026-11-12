import { appRoot } from './paths';

export interface SessionUser {
  id: string;
  display_name: string;
  email: string | null;
  role: 'user' | 'admin';
  /** Portrait advertised by the OIDC provider (authentik `picture` claim);
   * null for local accounts. */
  avatar_url?: string | null;
  /** True for password-backed accounts (can change their password). */
  local?: boolean;
}

export interface SessionState {
  authenticated: boolean;
  localEnabled: boolean;
  registrationEnabled: boolean;
  /** Registration additionally requires an invite code. */
  inviteRequired?: boolean;
  oidcEnabled: boolean;
  user?: SessionUser;
  csrfToken?: string;
}

export class ApiError extends Error {
  constructor(readonly status: number, message: string) {
    super(message);
  }
}

export async function api<T>(path: string, init: RequestInit = {}, csrfToken?: string): Promise<T> {
  const headers = new Headers(init.headers);
  if (csrfToken && !['GET', 'HEAD'].includes((init.method ?? 'GET').toUpperCase())) headers.set('X-CSRF-Token', csrfToken);
  const response = await fetch(new URL(path, appRoot()), { ...init, headers, credentials: 'same-origin' });
  if (!response.ok) {
    let message = '请求失败';
    try {
      const body = (await response.json()) as { detail?: string };
      message = body.detail ?? message;
    } catch {
      // The reverse proxy may return a non-JSON error before the API starts.
    }
    throw new ApiError(response.status, message);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

/** Upload with byte-level progress, which fetch cannot report. Resolves the
 * parsed JSON body; rejects with an ApiError carrying the server's detail. */
export function uploadWithProgress<T>(path: string, body: FormData, csrfToken: string | undefined, onProgress: (fraction: number) => void): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const request = new XMLHttpRequest();
    request.open('POST', new URL(path, appRoot()).href, true);
    request.withCredentials = true;
    if (csrfToken) request.setRequestHeader('X-CSRF-Token', csrfToken);
    request.upload.addEventListener('progress', (event) => {
      if (event.lengthComputable) onProgress(event.loaded / event.total);
    });
    request.addEventListener('load', () => {
      if (request.status >= 200 && request.status < 300) {
        try {
          resolve((request.responseText ? JSON.parse(request.responseText) : undefined) as T);
        } catch {
          resolve(undefined as T);
        }
        return;
      }
      let message = '上传失败';
      try {
        message = (JSON.parse(request.responseText) as { detail?: string }).detail ?? message;
      } catch {
        // Non-JSON error (e.g. a proxy 413); keep the default message.
      }
      reject(new ApiError(request.status, message));
    });
    request.addEventListener('error', () => reject(new ApiError(0, '网络错误，上传中断')));
    request.send(body);
  });
}

export async function getSession(): Promise<SessionState> {
  try {
    return await api<SessionState>('api/v1/auth/me');
  } catch {
    // The static wall remains usable during an API rollout or while an old
    // image is still running; in that state favourites stay browser-local.
    return { authenticated: false, localEnabled: false, registrationEnabled: false, oidcEnabled: false };
  }
}
