import { inferDomain, normalizeEpistemicType } from "../utils/receipt.js";

export default function ClaimRow({ claim, onViewEvidence }) {
  const ep = normalizeEpistemicType(claim);
  const domain = inferDomain(claim.statement);
  const risk = (claim.implication_risk || "").toLowerCase() === "high";

  const primaryEntity = (claim.entities && claim.entities[0]) || null;

  return (
    <div className="claim-row">
      <div className="claim-row-top">
        <span
          className={`epistemic-icon ${ep}`}
          title={ep}
          aria-label={ep}
        />
        <p className="claim-statement">&ldquo;{claim.statement}&rdquo;</p>
      </div>
      <div className="claim-meta-row">
        <span className="domain-tag">{domain}</span>
        <span className={`type-tag ${ep}`}>
          {ep === "observed" ? "Observed" : ep === "inferred" ? "Inferred" : "Unknown"}
        </span>
        {risk ? <span className="risk-badge">⚠ High</span> : null}
      </div>
      {(claim.entities && claim.entities.length > 0) ? (
        <button
          type="button"
          className="claim-evidence-link"
          onClick={() => onViewEvidence(primaryEntity)}
        >
          View evidence →
        </button>
      ) : null}
    </div>
  );
}
