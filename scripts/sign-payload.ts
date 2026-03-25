/**
 * Reads a FrameReceiptPayload JSON object from stdin, signs it, prints signed JSON to stdout.
 * Used by apps/api async jobs (e.g. FetchAdapter) — same signing as other receipt pipelines.
 */
import { readFileSync } from "node:fs";
import type { FrameReceiptPayload } from "@frame/types";
import { loadFramePrivateKeyFromEnv, signReceipt } from "../packages/signing/dist/index.js";

const stdin = readFileSync(0, "utf8");
const payload = JSON.parse(stdin) as FrameReceiptPayload;
const privateKey = loadFramePrivateKeyFromEnv();
const signed = signReceipt(payload, { privateKey });
process.stdout.write(`${JSON.stringify(signed)}\n`);
