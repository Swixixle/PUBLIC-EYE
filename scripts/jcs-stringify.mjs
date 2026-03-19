#!/usr/bin/env node
/**
 * Emit RFC 8785 JCS for JSON read from stdin.
 * Used by apps/api to match TypeScript `canonicalize` output exactly.
 */
import * as canonicalizeModule from "canonicalize";
const canonicalize = canonicalizeModule.default;
import fs from "node:fs";

const input = fs.readFileSync(0, "utf8");
const obj = JSON.parse(input);
const out = canonicalize(obj);
if (typeof out !== "string") {
  process.stderr.write("canonicalize returned non-string\n");
  process.exit(1);
}
process.stdout.write(out);
