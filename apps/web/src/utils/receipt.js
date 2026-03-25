/** Strip non-cryptographic fields before POST /v1/verify-receipt (matches Rabbit Hole web client). */
export function stripReceiptUrl(obj) {
  if (!obj || typeof obj !== "object") return obj;
  const {
    receiptUrl,
    extractedClaimObjects,
    transcript,
    sourceUrl,
    podcastTitle,
    note,
    ...rest
  } = obj;
  return rest;
}

export function inferDomain(statement) {
  const t = (statement || "").toLowerCase();
  if (/fec|campaign|donor|contribution|pac|\$|dollar|million|finance|dark money/.test(t)) {
    return "Financial";
  }
  if (/court|statute|law|legal|lawsuit|doj|§/.test(t)) return "Legal";
  if (/foreign|fara|embassy|minister|abroad|nato/.test(t)) return "Foreign";
  if (/vote|bill|senate|house|congress|record|voting|passed/.test(t)) return "Voting";
  return "General";
}

export function normalizeEpistemicType(claim) {
  const t = (claim.type || "observed").toLowerCase();
  if (t === "inferred" || t === "observation_inferred") return "inferred";
  if (t === "unknown" || t === "epistemic_unknown") return "unknown";
  return "observed";
}

export function collectEntitiesFromReceipt(receipt) {
  const meta = receipt.meta || {};
  const fromMeta = Array.isArray(meta.entities_detected) ? meta.entities_detected : [];
  const fromClaims = [];
  for (const c of receipt.claims || []) {
    for (const e of c.entities || []) {
      if (e && String(e).trim().length > 2) fromClaims.push(String(e).trim());
    }
  }
  const seen = new Set();
  const out = [];
  for (const n of [...fromMeta, ...fromClaims]) {
    const k = n.toLowerCase();
    if (seen.has(k)) continue;
    seen.add(k);
    out.push(n);
  }
  return out;
}

export function entityBadgeHint(entityName, claims) {
  const relevant = (claims || []).filter((c) =>
    (c.entities || []).some((e) => String(e).toLowerCase() === String(entityName).toLowerCase()),
  );
  const high = relevant.some((c) => (c.implication_risk || "").toLowerCase() === "high");
  const fin = relevant.some((c) => inferDomain(c.statement) === "Financial");
  if (high && fin) return { label: "High risk", tone: "red" };
  if (high) return { label: "High risk", tone: "red" };
  if (relevant.length && !high) return { label: "Clean", tone: "green" };
  return null;
}

export function guessEntityType(name) {
  const n = (name || "").toLowerCase();
  if (/(senator|rep\.|representative|governor|president)/.test(n)) return "politician";
  if (/(inc\.|llc|foundation|institute|party|ministry)/.test(n)) return "organization";
  return "public figure";
}

export function sourcesByAdapter(receipt, re) {
  return (receipt.sources || []).filter((s) => re.test(String(s.adapter || "").toLowerCase()));
}
