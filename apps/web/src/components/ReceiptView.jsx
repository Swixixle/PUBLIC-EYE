import { useState, useMemo } from "react";
import AccordionSection from "./AccordionSection.jsx";
import LayerZeroCard from "./LayerZeroCard.jsx";
import EntityPills from "./EntityPills.jsx";
import ClaimsList from "./ClaimsList.jsx";
import EntityPanel from "./EntityPanel.jsx";
import { receiptSignificanceLead } from "../utils/receipt.js";

function formatReceiptDate(iso) {
  if (!iso || iso === "unknown") return "—";
  try {
    return new Date(iso).toLocaleDateString(undefined, {
      year: "numeric",
      month: "short",
      day: "numeric",
    });
  } catch {
    return iso;
  }
}

/** Normalize layer_zero whether it is nested, camelCase, or a plain string. */
function layerZeroForDisplay(receipt) {
  if (!receipt || typeof receipt !== "object") return null;
  const raw =
    receipt.layer_zero ??
    receipt.layerZero ??
    (receipt.receipt && typeof receipt.receipt === "object"
      ? receipt.receipt.layer_zero ?? receipt.receipt.layerZero
      : undefined);
  if (raw == null) return null;
  if (typeof raw === "string") {
    const t = raw.trim();
    return t ? { text: t, salience_score: undefined } : null;
  }
  if (typeof raw === "object") {
    const text = String(raw.text ?? "").trim();
    if (!text) return null;
    const sal = raw.salience_score ?? raw.salience;
    return { text, salience_score: sal };
  }
  return null;
}

export default function ReceiptView({
  receipt,
  verifyOk,
  activeEntity,
  onSelectEntity,
  onClosePanel,
  claimsExpanded,
  onToggleClaims,
  epistemicFilter,
  domainFilter,
  onEpistemicFilter,
  onDomainFilter,
}) {
  const claims = receipt.claims || [];
  const lz = useMemo(() => layerZeroForDisplay(receipt), [receipt]);
  const entities = useMemo(() => {
    const meta = receipt.meta || {};
    const fromMeta = Array.isArray(meta.entities_detected) ? meta.entities_detected : [];
    const fromClaims = [];
    for (const c of claims) {
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
  }, [claims, receipt.meta]);

  const rid = receipt.receiptId || "—";

  const significanceLead = useMemo(() => receiptSignificanceLead(receipt), [receipt]);

  const [otherReceiptId, setOtherReceiptId] = useState("");
  const [compareEntity, setCompareEntity] = useState("");
  const [contraLoading, setContraLoading] = useState(false);
  const [contraError, setContraError] = useState(null);
  const [contraResult, setContraResult] = useState(null);

  const handleEvidence = (name) => {
    if (name) onSelectEntity(name);
  };

  const runContradiction = async () => {
    const b = otherReceiptId.trim();
    const ent = compareEntity.trim();
    if (!b || !ent) {
      setContraError("Enter the other receipt ID and entity name.");
      return;
    }
    setContraError(null);
    setContraLoading(true);
    setContraResult(null);
    try {
      const res = await fetch("/v1/contradiction-analysis", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          receipt_a_id: rid,
          receipt_b_id: b,
          entity_name: ent,
        }),
      });
      const text = await res.text();
      let data;
      try {
        data = JSON.parse(text);
      } catch {
        throw new Error(text || `HTTP ${res.status}`);
      }
      if (!res.ok) {
        throw new Error(
          typeof data.detail === "string"
            ? data.detail
            : JSON.stringify(data.detail || data),
        );
      }
      setContraResult(data);
    } catch (e) {
      setContraError(e.message || "Request failed");
    } finally {
      setContraLoading(false);
    }
  };

  return (
    <div className="receipt-view view-enter">
      <header className="receipt-sticky">
        <div className="receipt-sticky-left">
          <span className="receipt-sticky-mark">WHISTLE</span>
          <span className="receipt-sticky-sub">The record is sealed.</span>
        </div>
        <div className="receipt-sticky-right">
          <div className="receipt-id" title={rid}>
            {rid}
          </div>
          {verifyOk === true ? (
            <div className="verify-badge">✓ Verified</div>
          ) : verifyOk === false ? (
            <div className="verify-badge bad">Verification pending</div>
          ) : (
            <div className="verify-badge" style={{ color: "var(--text-muted)" }}>
              …
            </div>
          )}
        </div>
      </header>

      <div className={`receipt-layout ${activeEntity ? "has-panel" : ""}`}>
        <div className="receipt-main-col">
          <div className="receipt-body-wrap">
            {significanceLead ? (
              <div className="receipt-significance-lead" role="doc-abstract">
                <span className="receipt-significance-lead-label">SIGNIFICANCE</span>
                {significanceLead}
              </div>
            ) : null}
            {receipt.receipt_type === "article_analysis" ? (
              <div className="article-meta">
                <div className="article-pub">{receipt.article?.publication}</div>
                <div className="article-title">{receipt.article?.title}</div>
                <div className="article-topic">{receipt.article_topic}</div>
                <div className="claims-count">
                  {receipt.claims_extracted} claims extracted · {receipt.claims_verified?.length}{" "}
                  verified
                </div>
              </div>
            ) : null}
            {receipt.receipt_type === "article_analysis" &&
              (receipt.claims_verified || []).map((c, i) => (
                <AccordionSection
                  key={i}
                  title={c.claim}
                  statusRight={
                    c.verifications?.some((v) => v.status === "found") ? "found" : "deferred"
                  }
                  statusClass={
                    c.verifications?.some((v) => v.status === "found")
                      ? "status-found"
                      : "status-deferred"
                  }
                >
                  <div className="claim-detail">
                    <div>
                      <strong>Subject:</strong> {c.subject}
                    </div>
                    <div>
                      <strong>Type:</strong> {c.claim_type}
                    </div>
                    {c.cited_source ? (
                      <div>
                        <strong>Article cites:</strong> {c.cited_source}
                      </div>
                    ) : null}
                    {(c.verifications || []).map((v, j) => (
                      <div key={j} className="verification-row">
                        <span className="adapter-name">{v.adapter}</span>
                        <span className={`status-badge status-${v.status}`}>{v.status}</span>
                        {v.detail ? <span className="status-detail">{v.detail}</span> : null}
                      </div>
                    ))}
                  </div>
                </AccordionSection>
              ))}
            {lz ? <LayerZeroCard layerZero={lz} loading={false} /> : null}
            <EntityPills
              entities={entities}
              claims={claims}
              activeEntity={activeEntity}
              onSelect={onSelectEntity}
              loading={false}
            />
            <ClaimsList
              claims={claims}
              loading={false}
              claimsExpanded={claimsExpanded}
              onToggleExpand={onToggleClaims}
              epistemicFilter={epistemicFilter}
              domainFilter={domainFilter}
              onEpistemicFilter={onEpistemicFilter}
              onDomainFilter={onDomainFilter}
              onViewEvidence={handleEvidence}
            />

            <section className="contradiction-section" aria-labelledby="compare-heading">
              <h3 id="compare-heading">COMPARE WITH ANOTHER RECEIPT</h3>
              <div className="contradiction-form">
                <label>
                  Receipt ID
                  <input
                    type="text"
                    placeholder="Other receipt ID"
                    value={otherReceiptId}
                    onChange={(e) => setOtherReceiptId(e.target.value)}
                    autoComplete="off"
                  />
                </label>
                <label>
                  Entity name
                  <input
                    type="text"
                    placeholder="e.g. name on both recordings"
                    value={compareEntity}
                    onChange={(e) => setCompareEntity(e.target.value)}
                    autoComplete="off"
                  />
                </label>
                <button
                  type="button"
                  className="contradiction-submit"
                  onClick={runContradiction}
                  disabled={contraLoading || rid === "—"}
                >
                  {contraLoading ? "Analyzing…" : "Find Contradictions"}
                </button>
              </div>
              {contraError ? <p className="contradiction-error">{contraError}</p> : null}

              {contraResult ? (
                <div className="contradiction-dossier-footer" style={{ borderTop: "none", marginTop: 20 }}>
                  {contraResult.conflict_count === 0 ? (
                    <p className="contradiction-empty">
                      No contradictions found between these receipts for{" "}
                      <strong style={{ color: "var(--text)" }}>{contraResult.entity_name}</strong>.
                    </p>
                  ) : (
                    (contraResult.conflicts_found || []).map((c, i) => (
                      <div key={i} className="contradiction-card">
                        <div className="contradiction-card-head">⚡ Conflict documented</div>
                        <div className="contradiction-card-meta">
                          {c.conflict_type} · {typeof c.confidence === "number" ? c.confidence.toFixed(2) : c.confidence}
                        </div>
                        <p style={{ fontSize: "0.75rem", color: "var(--text-muted)", margin: "0 0 8px" }}>
                          Receipt A states ({formatReceiptDate(c.receipt_a_date)}):
                        </p>
                        <blockquote>&ldquo;{c.claim_a}&rdquo;</blockquote>
                        <p style={{ fontSize: "0.75rem", color: "var(--text-muted)", margin: "0 0 8px" }}>
                          Receipt B states ({formatReceiptDate(c.receipt_b_date)}):
                        </p>
                        <blockquote>&ldquo;{c.claim_b}&rdquo;</blockquote>
                        {c.time_delta_days != null ? (
                          <p className="delta">
                            {c.time_delta_days} days elapsed between these statements.
                          </p>
                        ) : null}
                        <p className="desc">{c.conflict_description}</p>
                      </div>
                    ))
                  )}
                  <p className="contradiction-dossier-footer">
                    Contradiction record:{" "}
                    <span className="hash">{contraResult.dossier_hash}</span>
                  </p>
                  {contraResult.disclaimer ? (
                    <p className="contradiction-disclaimer">{contraResult.disclaimer}</p>
                  ) : null}
                </div>
              ) : null}
            </section>
          </div>
        </div>

        {activeEntity ? (
          <EntityPanel entityName={activeEntity} receipt={receipt} onClose={onClosePanel} />
        ) : null}
      </div>
    </div>
  );
}
