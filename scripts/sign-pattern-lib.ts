/**
 * Signs each pattern record individually (JCS payload excludes signature metadata).
 * Requires: `npm run build`, repo-root `signing-keys.json` from `generate-keypair.ts`.
 */
import { readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { signRecord } from "../packages/signing/dist/index.js";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const patternsPath = join(root, "packages/pattern-lib/patterns.json");
const keysPath = join(root, "signing-keys.json");

const keys = JSON.parse(readFileSync(keysPath, "utf8")) as { privateKey: string; publicKey: string };
if (!keys.privateKey?.trim()) {
  throw new Error("signing-keys.json missing privateKey");
}

const patterns = JSON.parse(readFileSync(patternsPath, "utf8")) as unknown;
if (!Array.isArray(patterns)) {
  throw new Error("patterns.json must be a top-level array");
}

for (const rec of patterns) {
  if (typeof rec !== "object" || rec === null) continue;
  const meta = signRecord(rec as object, keys.privateKey);
  Object.assign(rec as object, meta);
}

writeFileSync(patternsPath, `${JSON.stringify(patterns, null, 2)}\n`, "utf8");
console.log(`Signed ${patterns.length} pattern record(s) → ${patternsPath}`);
