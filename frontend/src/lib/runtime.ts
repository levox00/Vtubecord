/**
 * Runtime URL helpers shared by the browser and the Vtubecord desktop shell.
 *
 * The development UI is served by Vite and can use its /api proxy. The
 * packaged Tauri window is served from the app's embedded origin, so API and
 * WebSocket traffic must go directly to the local FastAPI server instead.
 */

type DesktopWindow = Window & {
  __TAURI_INTERNALS__?: unknown;
};

export function isDesktopShell(): boolean {
  if (typeof window === "undefined") return false;
  const current = window as DesktopWindow;
  return Boolean(
    current.__TAURI_INTERNALS__ ||
      window.location.protocol === "tauri:" ||
      window.location.hostname === "tauri.localhost",
  );
}

const configuredBackendOrigin = (import.meta.env.VITE_BACKEND_ORIGIN || "").replace(/\/$/, "");

/** HTTP origin for the local FastAPI service, without a trailing slash. */
export function backendOrigin(): string {
  if (configuredBackendOrigin) return configuredBackendOrigin;
  if (isDesktopShell()) return "http://127.0.0.1:8000";
  return "";
}

/** API prefix usable in fetch calls from either runtime. */
export function apiBase(): string {
  return `${backendOrigin()}/api`;
}

/** Build a WebSocket URL for a backend path. */
export function backendWebSocketUrl(path: string): string {
  const origin = backendOrigin();
  if (origin) {
    const protocol = origin.startsWith("https:") ? "wss:" : "ws:";
    return `${protocol}//${origin.replace(/^https?:\/\//, "")}${path.startsWith("/") ? path : `/${path}`}`;
  }
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${window.location.host}${path.startsWith("/") ? path : `/${path}`}`;
}
