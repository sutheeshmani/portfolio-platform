// Server-only helpers. Never import this from a client component.

export const SESSION_COOKIE = "pp_session";
export const SESSION_MAX_AGE = 8 * 60 * 60; // seconds

export function apiBaseUrl(): string {
  const base = process.env.API_BASE_URL;
  if (!base) throw new Error("API_BASE_URL is not set");
  return base.replace(/\/+$/, "");
}

// Path segments the proxy will forward. Anything else (.., encoded slashes,
// query fragments smuggled into the path) is refused.
const SEGMENT = /^[A-Za-z0-9_-]+$/;

export function safeApiPath(segments: string[]): string | null {
  if (segments.length === 0 || segments.length > 8) return null;
  return segments.every((s) => SEGMENT.test(s)) ? segments.join("/") : null;
}
