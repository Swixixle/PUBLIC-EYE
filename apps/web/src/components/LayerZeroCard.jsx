export default function LayerZeroCard({ layerZero, loading }) {
  if (loading) {
    return (
      <div className="layer-zero-card">
        <div className="shell-label">LAYER ZERO</div>
        <div className="skeleton shell-layer-placeholder" style={{ minHeight: 80 }} />
      </div>
    );
  }

  let text = "";
  let sal;
  if (typeof layerZero === "string") {
    text = layerZero.trim();
  } else if (layerZero && typeof layerZero === "object") {
    text = String(layerZero.text ?? "").trim();
    sal = layerZero.salience_score ?? layerZero.salience;
  }

  if (!text) {
    return null;
  }

  return (
    <div className="layer-zero-card">
      <div className="layer-zero-head">
        <span aria-hidden="true">⚡</span> LAYER ZERO
      </div>
      <p className="layer-zero-text">{text}</p>
      {sal != null && sal !== "" ? (
        <div className="layer-zero-meta">salience: {Number(sal).toFixed(2)}</div>
      ) : null}
    </div>
  );
}
