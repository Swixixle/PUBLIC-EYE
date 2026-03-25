/**
 * Reads a FrameReceiptPayload JSON object from stdin, signs it, prints signed JSON to stdout.
 * Used by apps/api async jobs (e.g. FetchAdapter) — same signing as other receipt pipelines.
 */
import { readFileSync } from "node:fs";
import { createPrivateKey } from "node:crypto";
import type { FrameReceiptPayload } from "@frame/types";
import { signReceipt } from "../packages/signing/dist/index.js";

function getPrivateKeyPem(): string {
  const format = process.env.FRAME_KEY_FORMAT ?? "pem";
  const raw = process.env.FRAME_PRIVATE_KEY ?? "";
  if (!raw) throw new Error("Missing FRAME_PRIVATE_KEY in environment");
  if (format === "base64") {
    const decoded = Buffer.from(raw.trim(), "base64").toString("utf8");
    return decoded.replace(/\\n/g, "\n");
  }
  let pem = raw;
  if (!pem.includes("\n")) {
    pem = pem.replace(/\\n/g, "\n");
  }
  pem = pem.replace(/^["']|["']$/g, "");
  return pem.trim();
}

const stdin = readFileSync(0, "utf8");
const payload = JSON.parse(stdin) as FrameReceiptPayload;
const privateKey = createPrivateKey(getPrivateKeyPem());
const signed = signReceipt(payload, { privateKey });
process.stdout.write(`${JSON.stringify(signed)}\n`);
