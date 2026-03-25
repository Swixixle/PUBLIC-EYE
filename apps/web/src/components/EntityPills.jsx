import { entityBadgeHint } from "../utils/receipt.js";

export default function EntityPills({
  entities,
  claims,
  activeEntity,
  onSelect,
  loading,
}) {
  if (loading) {
    return (
      <div>
        <div className="shell-entities-title">ENTITIES DETECTED</div>
        <div className="entity-pills-strip">
          <div className="skeleton shell-pill" />
          <div className="skeleton shell-pill" />
          <div className="skeleton shell-pill" />
        </div>
      </div>
    );
  }

  if (!entities.length) {
    return (
      <div>
        <div className="shell-entities-title">ENTITIES DETECTED</div>
        <p style={{ color: "var(--text-muted)", fontSize: "0.85rem" }}>No named entities extracted.</p>
      </div>
    );
  }

  return (
    <div>
      <div className="shell-entities-title">ENTITIES DETECTED</div>
      <div className="entity-pills-strip">
        {entities.map((name) => {
          const hint = entityBadgeHint(name, claims);
          return (
            <button
              key={name}
              type="button"
              className={`entity-pill ${activeEntity === name ? "active" : ""}`}
              onClick={() => onSelect(name)}
            >
              {name}
              {hint && hint.tone === "red" ? (
                <span className="pill-badge red">{hint.label}</span>
              ) : null}
              {hint && hint.tone === "green" ? (
                <span className="pill-badge green">{hint.label}</span>
              ) : null}
            </button>
          );
        })}
      </div>
    </div>
  );
}
