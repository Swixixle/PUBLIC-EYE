#!/usr/bin/env node
/**
 * stdin: JSON
 * { "op": "getActor", "slug": "..." }
 * { "op": "getActorEvents", "slug": "..." }
 * { "op": "appendEvent", "slug": "...", "event": { ...ActorEvent } }
 * stdout: JSON (actor record, events array, or null for getActor miss)
 */
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const root = join(__dirname, "..");
const mod = await import(join(root, "packages/actor-ledger/dist/index.js"));
const { getActor, getActorEvents, appendEvent } = mod;

const input = JSON.parse(readFileSync(0, "utf8"));
let out;
switch (input.op) {
  case "getActor":
    out = getActor(input.slug);
    break;
  case "getActorEvents":
    out = getActorEvents(input.slug);
    break;
  case "appendEvent":
    out = appendEvent(input.slug, input.event);
    break;
  default:
    throw new Error(`unknown op: ${input.op}`);
}
process.stdout.write(JSON.stringify(out));
