/**
 * Regenerate apps/web/demo-payload.json from buildManchinFixture() using
 * FRAME_ED25519_PRIVATE_PEM in apps/api/.env (no FRAME_PRIVATE_KEY required).
 *
 * Run: npx tsx scripts/regen-demo-payload.ts
 */
import { createPrivateKey } from "node:crypto";
import { readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { signReceipt, verifyReceipt } from "../packages/signing/index.js";
import { buildManchinFixture } from "../packages/signing/__tests__/fixtures/manchin-payload.js";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(__dirname, "..");
const envPath = path.join(REPO_ROOT, "apps", "api", ".env");
const raw = readFileSync(envPath, "utf8");
const begin = raw.indexOf("-----BEGIN PRIVATE KEY-----");
const end = raw.indexOf("-----END PRIVATE KEY-----");
if (begin < 0 || end < 0) {
  throw new Error(`No PEM private key block in ${envPath}`);
}
const pem = raw.slice(begin, end + "-----END PRIVATE KEY-----".length).trim();
const privateKey = createPrivateKey(pem);
const signed = signReceipt(buildManchinFixture(), { privateKey });
const v = verifyReceipt(signed);
if (!v.ok) {
  throw new Error(`Self-verify failed: ${v.reasons.join("; ")}`);
}
const out = path.join(REPO_ROOT, "apps", "web", "demo-payload.json");
writeFileSync(out, `${JSON.stringify(signed, null, 2)}\n`);
console.error(`Wrote ${path.relative(REPO_ROOT, out)}`);
