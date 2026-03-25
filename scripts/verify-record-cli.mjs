#!/usr/bin/env node
/**
 * stdin: JSON { "record": object, "signature": string, "public_key": string }
 * stdout: JSON { "valid": boolean }
 */
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const root = join(__dirname, "..");
const { verifyRecord } = await import(join(root, "packages/signing/dist/index.js"));

const input = JSON.parse(readFileSync(0, "utf8"));
const valid = verifyRecord(input.record, input.signature, input.public_key);
process.stdout.write(JSON.stringify({ valid }));
