import { generateKeyPairSync } from "node:crypto";
import { describe, expect, it } from "vitest";
import { validateNarrative } from "../../narrative/governance.js";
import {
  computeContentHash,
  jcsCanonicalize,
  sha256HexOfJcs,
  signReceipt,
  verifyReceipt,
} from "../index.js";
import { buildManchinFixture } from "./fixtures/manchin-payload.js";

describe("Frame signing — Manchin fixture", () => {
  it("uses JCS (canonicalize) so key order does not change the hash", () => {
    const a = { z: 1, a: { m: 2, b: 3 } };
    const b = { a: { b: 3, m: 2 }, z: 1 };
    expect(jcsCanonicalize(a)).toBe(jcsCanonicalize(b));
    expect(sha256HexOfJcs(a)).toBe(sha256HexOfJcs(b));
  });

  it("rejects JSON.stringify for hashing contract (different output from JCS)", () => {
    const obj = { b: 1, a: 2 };
    const jcs = jcsCanonicalize(obj);
    const stringify = JSON.stringify(obj);
    expect(jcs).not.toBe(stringify);
  });

  it("passes narrative governance for the Manchin fixture", () => {
    const payload = buildManchinFixture();
    const violations = validateNarrative(payload.narrative, payload.sources);
    expect(violations).toEqual([]);
  });

  it("computes a stable content hash and signs with Ed25519", () => {
    const { privateKey } = generateKeyPairSync("ed25519");
    const base = buildManchinFixture();
    const hashBefore = computeContentHash(base);
    expect(hashBefore).toMatch(/^[a-f0-9]{64}$/);

    const signed = signReceipt(base, { privateKey });
    expect(signed.contentHash).toBe(hashBefore);
    expect(signed.signature.length).toBeGreaterThan(10);

    const v = verifyReceipt(signed);
    expect(v).toEqual({ ok: true, reasons: [] });
  });

  it("fails verification when narrative text is tampered after signing", () => {
    const { privateKey } = generateKeyPairSync("ed25519");
    const signed = signReceipt(buildManchinFixture(), { privateKey });
    const tampered = {
      ...signed,
      narrative: [
        ...signed.narrative.slice(0, -1),
        {
          ...signed.narrative[signed.narrative.length - 1]!,
          text: "Altered sentence that still cites the same source id.",
        },
      ],
    };
    const v = verifyReceipt(tampered);
    expect(v.ok).toBe(false);
    expect(v.reasons.length).toBeGreaterThan(0);
  });
});
