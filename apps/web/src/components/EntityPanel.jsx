import { useState } from "react";
import AccordionSection from "./AccordionSection.jsx";
import { guessEntityType, sourcesByAdapter } from "../utils/receipt.js";

export default function EntityPanel({ entityName, receipt, onClose }) {
  const [tableOpen, setTableOpen] = useState(false);
  const type = guessEntityType(entityName);

  const fecSources = sourcesByAdapter(receipt, /fec/);
  const legalSources = sourcesByAdapter(receipt, /court|legal|lda|lobby/);
  const metaNotes = (receipt.meta && receipt.meta.verification_notes) || [];

  const claimsForEntity = (receipt.claims || []).filter((c) =>
    (c.entities || []).some(
      (e) => String(e).toLowerCase() === String(entityName).toLowerCase(),
    ),
  );

  const narrative = (receipt.narrative || [])
    .map((n) => n.text || n)
    .filter(Boolean)
    .join("\n\n");

  const fecStatus =
    fecSources.length > 0
      ? `${fecSources.length} source${fecSources.length === 1 ? "" : "s"}`
      : "Pending";

  const revStatus = "Not in receipt";
  const faraStatus = "Not in receipt";
  const legalStatus =
    legalSources.length > 0
      ? `${legalSources.length} ref`
      : metaNotes.length
        ? `${metaNotes.length} notes`
        : "See sources";

  const votingStatus = "See narrative";

  return (
    <div className="entity-panel-root">
      <div
        className="entity-panel-backdrop"
        onClick={onClose}
        onKeyDown={(e) => e.key === "Escape" && onClose()}
        role="presentation"
      />
      <aside className="entity-panel">
        <div className="entity-panel-header">
          <button type="button" className="mobile-back" onClick={onClose}>
            ← Back to receipt
          </button>
          <div className="entity-panel-header-top">
            <div>
              <h2 className="entity-panel-title">{entityName}</h2>
              <span className="entity-type-badge">{type}</span>
            </div>
            <button
              type="button"
              className="entity-panel-close"
              onClick={onClose}
              aria-label="Close"
            >
              ✕
            </button>
          </div>
        </div>
        <div className="entity-panel-scroll">
          <AccordionSection
            title="FEC Financial Record"
            statusRight={fecStatus}
            statusClass={fecSources.length ? "emphasis" : ""}
            defaultOpen
          >
            <p>
              Public sources on this receipt that reference campaign finance or
              the FEC are listed below. Counts reflect what was attached at signing
              time.
            </p>
            {fecSources.length ? (
              <ul style={{ margin: "8px 0 0", paddingLeft: "18px" }}>
                {fecSources.slice(0, 6).map((s) => (
                  <li key={s.id || s.url} style={{ marginBottom: 6 }}>
                    <a
                      href={s.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      style={{ color: "var(--blue)" }}
                    >
                      {s.title || s.adapter || "Source"}
                    </a>
                  </li>
                ))}
              </ul>
            ) : (
              <p>No FEC-specific sources were merged for this entity on this receipt.</p>
            )}
            {claimsForEntity.length ? (
              <>
                <button
                  type="button"
                  className="inline-table-toggle"
                  onClick={() => setTableOpen(!tableOpen)}
                >
                  {tableOpen ? "Hide claims ↑" : "Show full table ↓"}
                </button>
                {tableOpen ? (
                  <table className="data-table">
                    <thead>
                      <tr>
                        <th>Claim</th>
                        <th>Risk</th>
                      </tr>
                    </thead>
                    <tbody>
                      {claimsForEntity.map((c) => (
                        <tr key={c.id || c.statement}>
                          <td>{(c.statement || "").slice(0, 200)}</td>
                          <td>{c.implication_risk || "—"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                ) : null}
              </>
            ) : null}
          </AccordionSection>

          <AccordionSection
            title="Revolving Door"
            statusRight={revStatus}
            statusClass="emphasis"
          >
            <p>
              Revolving-door dossier fields are assembled server-side when enabled;
              they are not always embedded in the signed podcast receipt. Check the
              Rabbit Hole API or entity record for full tables.
            </p>
          </AccordionSection>

          <AccordionSection
            title="FARA Cross-Reference"
            statusRight={faraStatus}
            statusClass="emphasis"
          >
            <p>
              FARA cross-reference data may appear on entity dossiers. This receipt
              does not embed a FARA chain unless the backend attached it.
            </p>
          </AccordionSection>

          <AccordionSection
            title="Legal Citations"
            statusRight={legalStatus}
            statusClass={legalSources.length ? "emphasis" : ""}
          >
            {legalSources.length ? (
              <ul style={{ margin: 0, paddingLeft: "18px" }}>
                {legalSources.map((s) => (
                  <li key={s.id || s.url} style={{ marginBottom: 6 }}>
                    <a
                      href={s.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      style={{ color: "var(--blue)" }}
                    >
                      {s.title || s.adapter}
                    </a>
                  </li>
                ))}
              </ul>
            ) : (
              <p>No separate legal-adapter rows; see primary sources on the receipt.</p>
            )}
          </AccordionSection>

          <AccordionSection title="Voting Record" statusRight={votingStatus}>
            <p>
              Voting summaries require legislative API configuration. Narrative lines
              may still reference recorded votes when present in the signed payload.
            </p>
          </AccordionSection>

          <AccordionSection title="Full Narrative" statusRight="Prose">
            <p style={{ whiteSpace: "pre-wrap", color: "var(--text)" }}>
              {narrative || "No narrative block on this receipt."}
            </p>
          </AccordionSection>

          <AccordionSection
            title="Verified Receipt"
            statusRight="Ed25519"
            statusClass="green"
          >
            <p className="mono-block">
              receiptId: {receipt.receiptId || "—"}
              <br />
              contentHash: {receipt.contentHash || "—"}
              <br />
              publicKey: {(receipt.publicKey || "").slice(0, 48)}…
            </p>
            <p className="verify-link" style={{ marginTop: 12 }}>
              Verify this receipt →
            </p>
            <p style={{ fontSize: "0.75rem", marginTop: 8 }}>
              POST the signed JSON to <code>/v1/verify-receipt</code> or use the ✓
              Verified badge on the receipt header.
            </p>
          </AccordionSection>
        </div>
      </aside>
    </div>
  );
}
