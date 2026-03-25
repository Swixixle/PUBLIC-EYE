#!/usr/bin/env node
/**
 * stdin: JSON
 * { "op": "append", "entry": DisputeEntry }
 * { "op": "get", "pattern_id": string | undefined }
 */
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const root = join(__dirname, "..");
const { appendDispute, getDisputes } = await import(
  join(root, "packages/dispute-log/dist/index.js"),
);

const input = JSON.parse(readFileSync(0, "utf8"));
if (input.op === "append") {
  process.stdout.write(JSON.stringify(appendDispute(input.entry)));
} else if (input.op === "get") {
  process.stdout.write(JSON.stringify(getDisputes(input.pattern_id)));
} else {
  throw new Error(`unknown op: ${input.op}`);
}
