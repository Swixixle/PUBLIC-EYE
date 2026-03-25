#!/usr/bin/env node
/**
 * stdin: JSON { "narrative": "..." } or { "url": "..." }
 * stdout: JSON SurfaceResult
 * env: ANTHROPIC_API_KEY (required)
 */
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const root = join(__dirname, "..");
const { getSurfaceLayer } = await import(join(root, "packages/adapters/dist/surface.js"));

const raw = readFileSync(0, "utf8");
const input = JSON.parse(raw);
const out = await getSurfaceLayer(input);
process.stdout.write(JSON.stringify(out));
