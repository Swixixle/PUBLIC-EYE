/**
 * API origin for `fetch`.
 * - Dev: empty → relative `/v1/*` (Vite proxy → localhost:8000).
 * - Prod: `VITE_API_BASE_URL` if set, else documented production API (override in Netlify env).
 */
const PROD_DEFAULT = "https://frame-2yxu.onrender.com";

export function getApiBase() {
  const raw = import.meta.env.VITE_API_BASE_URL;
  if (typeof raw === "string" && raw.trim()) return raw.trim().replace(/\/$/, "");
  if (import.meta.env.PROD) return PROD_DEFAULT.replace(/\/$/, "");
  return "";
}
