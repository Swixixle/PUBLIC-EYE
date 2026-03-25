import { createPrivateKey, createPublicKey, type KeyObject } from "node:crypto";

function normalizePemEnv(raw: string): string {
  let pem = raw.replace(/\\n/g, "\n");
  pem = pem.replace(/^["']|["']$/g, "");
  return pem.trim();
}

/**
 * FRAME_KEY_FORMAT=base64 may store either base64(PEM utf-8) or base64(PKCS#8 / SPKI DER),
 * depending on how the secret was generated (dashboards often use DER).
 */
function keyObjectFromBase64Secret(raw: string, kind: "private" | "public"): KeyObject {
  const buf = Buffer.from(raw.trim(), "base64");
  const asText = buf.toString("utf8");
  const looksPem =
    asText.includes("BEGIN") &&
    (kind === "private" ? asText.includes("PRIVATE") : asText.includes("PUBLIC"));
  if (looksPem) {
    const pem = normalizePemEnv(asText);
    return kind === "private" ? createPrivateKey(pem) : createPublicKey(pem);
  }
  if (kind === "private") {
    return createPrivateKey({ key: buf, format: "der", type: "pkcs8" });
  }
  return createPublicKey({ key: buf, format: "der", type: "spki" });
}

export function loadFramePrivateKeyFromEnv(): KeyObject {
  const format = (process.env.FRAME_KEY_FORMAT ?? "pem").toLowerCase();
  const raw = process.env.FRAME_PRIVATE_KEY ?? "";
  if (!raw) throw new Error("Missing FRAME_PRIVATE_KEY in environment");
  if (format === "base64") {
    return keyObjectFromBase64Secret(raw, "private");
  }
  return createPrivateKey(normalizePemEnv(raw));
}

export function loadFramePublicKeyFromEnv(): KeyObject {
  const format = (process.env.FRAME_KEY_FORMAT ?? "pem").toLowerCase();
  const raw = process.env.FRAME_PUBLIC_KEY ?? "";
  if (!raw) throw new Error("Missing FRAME_PUBLIC_KEY in environment");
  if (format === "base64") {
    return keyObjectFromBase64Secret(raw, "public");
  }
  return createPublicKey(normalizePemEnv(raw));
}
