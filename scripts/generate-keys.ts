#!/usr/bin/env tsx
/**
 * Generate an Ed25519 keypair for Frame receipt signing (PEM format).
 */
import { generateKeyPairSync } from "node:crypto";

const { publicKey, privateKey } = generateKeyPairSync("ed25519", {
  publicKeyEncoding: { type: "spki", format: "pem" },
  privateKeyEncoding: { type: "pkcs8", format: "pem" },
});

console.log("--- FRAME_ED25519_PRIVATE_PEM ---");
console.log(privateKey.trimEnd());
console.log("--- FRAME_ED25519_PUBLIC_PEM ---");
console.log(publicKey.trimEnd());
console.log(
  "\nStore private material in a secrets manager; never commit PEM to git.",
);
