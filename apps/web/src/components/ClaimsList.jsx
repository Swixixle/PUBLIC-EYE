import ClaimRow from "./ClaimRow.jsx";
import { inferDomain, normalizeEpistemicType } from "../utils/receipt.js";

export default function ClaimsList({
  claims,
  loading,
  claimsExpanded,
  onToggleExpand,
  epistemicFilter,
  domainFilter,
  onEpistemicFilter,
  onDomainFilter,
  onViewEvidence,
}) {
  const filtered = (claims || []).filter((c) => {
    const ep = normalizeEpistemicType(c);
    if (epistemicFilter !== "all" && ep !== epistemicFilter) return false;

    const d = inferDomain(c.statement).toLowerCase();
    if (domainFilter !== "all" && domainFilter !== d) return false;
    return true;
  });

  const shown = claimsExpanded ? filtered : filtered.slice(0, 5);

  if (loading) {
    return (
      <div>
        <div className="claims-header-row">
          <span className="claims-header">CLAIMS</span>
        </div>
        <div className="skeleton shell-row" />
        <div className="skeleton shell-row" />
        <div className="skeleton shell-row" />
      </div>
    );
  }

  return (
    <div>
      <div className="claims-header-row">
        <span className="claims-header">CLAIMS</span>
        <span className="claims-count">{filtered.length}</span>
      </div>

      <div className="filter-rows">
        <div className="filter-row">
          {["all", "observed", "inferred", "unknown"].map((k) => (
            <button
              key={k}
              type="button"
              className={`filter-btn ${epistemicFilter === k ? "on" : ""}`}
              onClick={() => onEpistemicFilter(k)}
            >
              {k === "all" ? "All" : k.charAt(0).toUpperCase() + k.slice(1)}
            </button>
          ))}
        </div>
        <div className="filter-row">
          {[
            ["all", "All"],
            ["financial", "Financial"],
            ["legal", "Legal"],
            ["foreign", "Foreign"],
            ["voting", "Voting"],
          ].map(([k, label]) => (
            <button
              key={k}
              type="button"
              className={`filter-btn ${domainFilter === k ? "on" : ""}`}
              onClick={() => onDomainFilter(k)}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      {shown.map((c) => (
        <ClaimRow key={c.id || c.statement} claim={c} onViewEvidence={onViewEvidence} />
      ))}

      {filtered.length > 5 ? (
        <button type="button" className="show-all-claims" onClick={onToggleExpand}>
          {claimsExpanded
            ? "Show fewer ↑"
            : `Show all ${filtered.length} claims ↓`}
        </button>
      ) : null}
    </div>
  );
}
