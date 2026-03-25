import { buildLive990Receipt } from "../packages/sources/index.js";
import {
  loadFramePrivateKeyFromEnv,
  signReceipt,
  verifyReceipt,
} from "../packages/signing/dist/index.js";

const orgName = process.argv[2]?.trim() ?? "";
const ein = process.argv[3]?.trim() || undefined;

if (!orgName) {
  console.error(JSON.stringify({ error: "orgName required" }));
  process.exit(1);
}

const privateKey = loadFramePrivateKeyFromEnv();
const payload = await buildLive990Receipt(orgName, ein);
const signed = signReceipt(payload, { privateKey });
const v = verifyReceipt(signed);
if (!v.ok) {
  throw new Error(`Self-verify failed: ${v.reasons.join("; ")}`);
}
process.stdout.write(`${JSON.stringify(signed)}\n`);
