#!/usr/bin/env tsx
/**
 * Generate an Ed25519 keypair for Frame receipt signing (PEM format).
 *
 * Default: print PEMs to stdout (legacy; avoid in shared chat logs).
 * Safe: `npx tsx scripts/generate-keys.ts --write-env` writes apps/api/.env only.
 */
import { generateKeyPairSync } from "node:crypto";
import { mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const writeEnv = process.argv.includes("--write-env");

const { publicKey, privateKey } = generateKeyPairSync("ed25519", {
  publicKeyEncoding: { type: "spki", format: "pem" },
  privateKeyEncoding: { type: "pkcs8", format: "pem" },
});

if (writeEnv) {
  const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
  const apiDir = path.join(root, "apps", "api");
  mkdirSync(apiDir, { recursive: true });
  const envPath = path.join(apiDir, ".env");
  const body =
    `FRAME_PRIVATE_KEY=${JSON.stringify(privateKey.trimEnd())}\n` +
    `FRAME_PUBLIC_KEY=${JSON.stringify(publicKey.trimEnd())}\n`;
  writeFileSync(envPath, body, { mode: 0o600 });
  console.log("Keys written to apps/api/.env — do not print to screen");
  process.exit(0);
}

console.log("--- FRAME_ED25519_PRIVATE_PEM ---");
console.log(privateKey.trimEnd());
console.log("--- FRAME_ED25519_PUBLIC_PEM ---");
console.log(publicKey.trimEnd());
console.log(
  "\nStore private material in a secrets manager; never commit PEM to git.",
);
