/**
 * One-time: writes repo-root `signing-keys.json` (gitignored) — pattern library root of trust.
 * Run: `npm run build && npx tsx scripts/generate-keypair.ts`
 */
import { writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { generateKeypair } from "../packages/signing/dist/index.js";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const { privateKey, publicKey } = generateKeypair();
writeFileSync(
  join(root, "signing-keys.json"),
  `${JSON.stringify({ privateKey, publicKey }, null, 2)}\n`,
  "utf8",
);
console.log("Wrote signing-keys.json (gitignored)");
