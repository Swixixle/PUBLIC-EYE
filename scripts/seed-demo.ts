/**
 * Build a real signed Manchin receipt using keys from apps/api/.env
 * and write apps/web/demo-payload.json for the static demo.
 *
 * Run: `npx tsx scripts/seed-demo.ts` (ESM; plain `ts-node` needs extra ESM flags).
 */
import { createPrivateKey, createPublicKey } from "node:crypto";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { signReceipt, verifyReceipt } from "../packages/signing/dist/index.js";
import { buildManchinFixture } from "../packages/signing/__tests__/fixtures/manchin-payload.js";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(__dirname, "..");
const ENV_PATH = path.join(REPO_ROOT, "apps", "api", ".env");
const OUT_JSON = path.join(REPO_ROOT, "apps", "web", "demo-payload.json");

/** Minimal .env parser: KEY=value or KEY="JSON-encoded string" (PEMs use JSON.stringify newlines). */
function loadEnvFile(filePath: string): void {
  const raw = readFileSync(filePath, "utf8");
  for (const line of raw.split(/\r?\n/)) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#")) continue;
    const eq = trimmed.indexOf("=");
    if (eq === -1) continue;
    const key = trimmed.slice(0, eq).trim();
    let val = trimmed.slice(eq + 1).trim();
    if (
      (val.startsWith('"') && val.endsWith('"')) ||
      (val.startsWith("'") && val.endsWith("'"))
    ) {
      val = JSON.parse(val) as string;
    }
    process.env[key] = val;
  }
}

function pemFromEnv(name: string): string {
  const v = process.env[name];
  if (!v || v.trim() === "") {
    throw new Error(`Missing ${name} in ${ENV_PATH}`);
  }
  return v.replace(/\\n/g, "\n").trim();
}

loadEnvFile(ENV_PATH);

const privatePem = pemFromEnv("FRAME_PRIVATE_KEY");
const publicPem = pemFromEnv("FRAME_PUBLIC_KEY");

const privateKey = createPrivateKey(privatePem);
const envDer = createPublicKey(publicPem).export({
  type: "spki",
  format: "der",
}) as Buffer;
const derivedDer = createPublicKey(privateKey).export({
  type: "spki",
  format: "der",
}) as Buffer;
if (!envDer.equals(derivedDer)) {
  throw new Error(
    "FRAME_PUBLIC_KEY does not match FRAME_PRIVATE_KEY (SPKI DER mismatch).",
  );
}

const payload = buildManchinFixture();
const signed = signReceipt(payload, { privateKey });

const v = verifyReceipt(signed);
if (!v.ok) {
  throw new Error(`Self-verify failed: ${v.reasons.join("; ")}`);
}

const json = `${JSON.stringify(signed, null, 2)}\n`;
console.log(json);

mkdirSync(path.dirname(OUT_JSON), { recursive: true });
writeFileSync(OUT_JSON, json, "utf8");
console.error(`Wrote ${path.relative(REPO_ROOT, OUT_JSON)}`);
