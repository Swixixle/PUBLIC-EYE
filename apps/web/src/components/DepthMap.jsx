import { useCallback, useEffect, useMemo, useState } from "react";

import { getApiBase } from "../apiBase.js";

const API = getApiBase();

/** Verbatim opening copy under ## Tone & Voice in `docs/RABBIT_HOLE_CONTEXT.md`. */
const OPENING_DISCLAIMER =
  "Rabbit Hole shows what the cited record states and what it does not state. It does not issue verdicts, moral judgments, or recommendations about what you should do or believe. Every surfaced line ties to a source id or to an explicit unknown; if something is missing from the record, the interface says so. This is a navigational map of public material at retrieval time, not legal advice, medical advice, personal advice, or proof of anyone's intent.";

/** Spec-aligned tier colors: green / blue / grey-blue / amber / orange / grey */
const TIER_BADGE = {
  official_primary: { bg: "#15803d", fg: "#ecfdf5", label: "official primary" },
  official_secondary: { bg: "#1d4ed8", fg: "#eff6ff", label: "official secondary" },
  aggregated_registry: { bg: "#475569", fg: "#e2e8f0", label: "aggregated registry" },
  cross_corroborated: { bg: "#d97706", fg: "#0f172a", label: "cross corroborated" },
  single_source: { bg: "#ea580c", fg: "#fff7ed", label: "single source" },
  structural_heuristic: { bg: "#64748b", fg: "#f8fafc", label: "structural heuristic" },
  PATTERN_MATCH: { bg: "#6d28d9", fg: "#f5f3ff", label: "pattern match" },
};

function TierBadge({ tier }) {
  const k = tier === "PATTERN_MATCH" ? "PATTERN_MATCH" : tier;
  const s = TIER_BADGE[k] || TIER_BADGE.structural_heuristic;
  return (
    <span
      className="depth-tier-badge"
      style={{ background: s.bg, color: s.fg }}
      title={s.label}
    >
      {String(tier).replace(/_/g, " ")}
    </span>
  );
}

function DisputePanel({ patternId, onClose }) {
  const [counter, setCounter] = useState("");
  const [note, setNote] = useState("");
  const [loading, setLoading] = useState(false);
  const [successId, setSuccessId] = useState(null);
  const [err, setErr] = useState(null);

  const submit = async () => {
    setErr(null);
    setSuccessId(null);
    if (!counter.trim()) {
      setErr("Counter-evidence is required.");
      return;
    }
    setLoading(true);
    try {
      const res = await fetch(`${API}/v1/dispute`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          pattern_id: patternId,
          counter_evidence: counter.trim(),
          submitter_note: note.trim() || null,
        }),
      });
      const data = await res.json().catch(() => ({}));
      if (res.status === 404 && data?.detail?.absent) {
        const d = data.detail;
        setErr(
          typeof d === "object" && d?.reason != null
            ? String(d.reason)
            : JSON.stringify(d),
        );
        return;
      }
      if (!res.ok) {
        setErr(data?.detail ? JSON.stringify(data.detail) : `HTTP ${res.status}`);
        return;
      }
      if (data.dispute_id) setSuccessId(data.dispute_id);
    } catch (e) {
      setErr(e.message || "Request failed");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="depth-dispute-panel">
      <textarea
        className="depth-dispute-textarea"
        placeholder="Counter-evidence (required)"
        value={counter}
        onChange={(e) => setCounter(e.target.value)}
        rows={4}
      />
      <input
        className="depth-dispute-input"
        type="text"
        placeholder="Submitter note (optional)"
        value={note}
        onChange={(e) => setNote(e.target.value)}
      />
      <div className="depth-dispute-actions">
        <button type="button" className="depth-btn depth-btn-primary" disabled={loading} onClick={submit}>
          {loading ? "Submitting…" : "Submit dispute"}
        </button>
        <button type="button" className="depth-btn depth-btn-ghost" onClick={onClose}>
          Cancel
        </button>
      </div>
      {successId ? (
        <p className="depth-dispute-success">
          Filed: dispute_id <code>{successId}</code>
        </p>
      ) : null}
      {err ? <p className="depth-dispute-error">{err}</p> : null}
    </div>
  );
}

function SurfaceTraceFields({ trace }) {
  return (
    <>
      <p className="depth-what">{trace.what}</p>
      <div className="depth-meta-row">
        <TierBadge tier={trace.what_confidence_tier} />
      </div>
      <div className="depth-who">
        <strong>Who</strong>
        <ul>
          {(trace.who || []).map((w) => (
            <li key={w.name}>
              {w.name} <TierBadge tier={w.confidence_tier} />
            </li>
          ))}
        </ul>
      </div>
      <div className="depth-when">
        <strong>When</strong>
        <p>{trace.when?.earliest_appearance}</p>
        <p className="depth-muted">{trace.when?.source}</p>
        <TierBadge tier={trace.when?.confidence_tier} />
      </div>
      {trace.absent_fields && trace.absent_fields.length > 0 ? (
        <div className="depth-absent-fields">
          <strong>Absent fields</strong>
          <ul className="depth-absent-list">
            {trace.absent_fields.map((f) => (
              <li key={f}>{f}</li>
            ))}
          </ul>
        </div>
      ) : null}
    </>
  );
}

function LayerCard({ layer, children }) {
  const available = layer.depth_available;
  const sealedFloor = layer.layer_number === 6 && !available;

  return (
    <article
      className={`depth-layer-card ${available ? "depth-layer--available" : "depth-layer--limited"} ${sealedFloor ? "depth-layer--sealed-floor" : ""}`}
    >
      <div className="depth-layer-head">
        <span className="depth-layer-num">Layer {layer.layer_number}</span>
        <span className="depth-layer-name">{layer.layer_name}</span>
        <span
          className={`depth-availability-pill ${available ? "depth-availability--yes" : "depth-availability--no"}`}
        >
          {available ? "Depth available" : "Floor sealed"}
        </span>
      </div>
      <p className="depth-layer-contents">{layer.contents}</p>
      <div className="depth-layer-tiers">
        {(layer.confidence_tiers_allowed || []).map((t) => (
          <TierBadge key={t} tier={t} />
        ))}
      </div>
      {!available ? (
        <p className="depth-limit-reason">
          {layer.depth_limit_reason || "This jurisdiction is not yet wired."}
        </p>
      ) : null}
      {children}
    </article>
  );
}

export default function DepthMap() {
  const [layers, setLayers] = useState([]);
  const [mapError, setMapError] = useState(null);
  const [narrative, setNarrative] = useState("");
  const [surfaceResult, setSurfaceResult] = useState(null);
  const [surfaceUnavailable, setSurfaceUnavailable] = useState(false);
  const [surfaceError, setSurfaceError] = useState(null);
  const [patternResult, setPatternResult] = useState(null);
  const [patternError, setPatternError] = useState(null);
  const [searchBusy, setSearchBusy] = useState(false);
  const [openDispute, setOpenDispute] = useState(null);
  const [exampleTrace, setExampleTrace] = useState(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch(`${API}/v1/surface/slenderman`);
        if (!res.ok || cancelled) return;
        const data = await res.json().catch(() => null);
        if (!cancelled && data && typeof data === "object") setExampleTrace(data);
      } catch {
        /* silent — no error UI for baseline fetch */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch(`${API}/v1/depth-map`);
        if (!res.ok) throw new Error(`depth-map ${res.status}`);
        const data = await res.json();
        const ls = (data.layers || []).slice().sort((a, b) => a.layer_number - b.layer_number);
        if (!cancelled) setLayers(ls);
      } catch (e) {
        if (!cancelled) setMapError(e.message || "Failed to load depth map");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const headerLine = useMemo(() => {
    const hasSurface = surfaceResult && !surfaceUnavailable;
    const hasPattern = patternResult !== null;
    if (!hasSurface && !hasPattern && !surfaceUnavailable) {
      return "Depth map · Layer 1 of 6 (entry point)";
    }
    if (surfaceUnavailable && !hasPattern) {
      return "Layer 1 of 6 · Surface offline · awaiting depth";
    }
    const idx = [];
    if (hasSurface || surfaceUnavailable) idx.push(1);
    if (hasPattern) idx.push(5);
    if (idx.length === 0) return "Layer 1 of 6";
    const uniq = [...new Set(idx)].sort((a, b) => a - b);
    return `Layer ${uniq.join(" & ")} of 6`;
  }, [surfaceResult, surfaceUnavailable, patternResult]);

  const onSearch = useCallback(
    async (e) => {
      e.preventDefault();
      const text = narrative.trim();
      if (!text) return;
      setSearchBusy(true);
      setExampleTrace(null);
      setSurfaceResult(null);
      setSurfaceUnavailable(false);
      setSurfaceError(null);
      setPatternResult(null);
      setPatternError(null);
      setOpenDispute(null);

      const [sRes, pRes] = await Promise.all([
        fetch(`${API}/v1/surface`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ narrative: text }),
        }),
        fetch(`${API}/v1/pattern-match`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ narrative: text }),
        }),
      ]);

      if (sRes.status === 503) {
        setSurfaceUnavailable(true);
        setSurfaceError(null);
      } else if (sRes.ok) {
        setSurfaceResult(await sRes.json());
        setSurfaceError(null);
      } else {
        setSurfaceUnavailable(false);
        setSurfaceResult(null);
        try {
          const d = await sRes.json();
          const det = d?.detail;
          setSurfaceError(
            typeof det === "string" ? det : det != null ? JSON.stringify(det) : `HTTP ${sRes.status}`,
          );
        } catch {
          setSurfaceError(`HTTP ${sRes.status}`);
        }
      }

      if (pRes.ok) {
        setPatternResult(await pRes.json());
      } else {
        setPatternError(`Pattern match failed (${pRes.status})`);
      }

      setSearchBusy(false);
    },
    [narrative],
  );

  const layerByNum = (n) => layers.find((l) => l.layer_number === n);

  return (
    <div className="depth-map-root">
      <header className="depth-nav-header">
        <h1 className="depth-title">Rabbit Hole</h1>
        <p className="depth-tagline">
          <em>There is enough O2 even miles down the Rabbit Hole.</em>
        </p>
        <p className="depth-disclaimer">{OPENING_DISCLAIMER}</p>
        <p className="depth-position">{headerLine}</p>
      </header>

      <form className="depth-search" onSubmit={onSearch}>
        <label className="depth-search-label" htmlFor="depth-narrative">
          Narrative
        </label>
        <div className="depth-search-row">
          <input
            id="depth-narrative"
            className="depth-search-input"
            type="text"
            placeholder="Paste or type a claim, excerpt, or URL context as narrative…"
            value={narrative}
            onChange={(e) => setNarrative(e.target.value)}
          />
          <button type="submit" className="depth-btn depth-btn-primary" disabled={searchBusy}>
            {searchBusy ? "Tracing…" : "Trace at depth"}
          </button>
        </div>
      </form>

      {mapError ? <p className="depth-banner depth-banner-error">{mapError}</p> : null}

      <div className="depth-stack">
        {[1, 2, 3, 4, 5, 6].map((num) => {
          const layer = layerByNum(num);
          if (!layer) {
            return (
              <div key={num} className="depth-layer-placeholder">
                <p>Layer {num}</p>
                <p className="depth-limited-msg">Limited sourcing available at this depth.</p>
              </div>
            );
          }

          const isL1 = num === 1;
          const isL5 = num === 5;

          return (
            <LayerCard key={layer.layer_number} layer={layer}>
              {isL1 ? (
                <div className="depth-layer-inline">
                  {surfaceUnavailable ? (
                    <p className="depth-surface-offline">
                      Surface analysis unavailable: credits offline
                    </p>
                  ) : null}
                  {surfaceError ? <p className="depth-banner-error depth-surface-err">{surfaceError}</p> : null}
                  {searchBusy && isL1 ? (
                    <p className="depth-muted depth-trace-hint">Tracing surface…</p>
                  ) : null}
                  {!surfaceUnavailable && !surfaceResult && !searchBusy ? (
                    <p className="depth-limited-msg">Limited sourcing available at this depth.</p>
                  ) : null}
                  {!surfaceUnavailable && surfaceResult ? (
                    <div className="depth-surface-result">
                      <h3 className="depth-inline-title">Surface trace</h3>
                      <SurfaceTraceFields trace={surfaceResult} />
                    </div>
                  ) : null}
                  {exampleTrace && !surfaceResult && !searchBusy ? (
                    <div className="depth-example-trace">
                      <p className="depth-example-label">
                        <em>Example trace — Slenderman (inoculation baseline)</em>
                      </p>
                      <SurfaceTraceFields trace={exampleTrace} />
                      <p className="depth-example-slenderman-note">
                        <em>
                          Slenderman was manufactured. We know exactly when, by whom, on which forum. This
                          is what a fully traced narrative looks like.
                        </em>
                      </p>
                    </div>
                  ) : null}
                </div>
              ) : null}

              {num === 2 || num === 3 || num === 4 ? (
                <p className="depth-limited-msg">Limited sourcing available at this depth.</p>
              ) : null}

              {isL5 ? (
                <div className="depth-layer-inline">
                  {searchBusy && isL5 ? (
                    <p className="depth-muted depth-trace-hint">Matching patterns…</p>
                  ) : null}
                  {!patternResult && !patternError && !searchBusy ? (
                    <p className="depth-limited-msg">Limited sourcing available at this depth.</p>
                  ) : null}
                  {patternError ? <p className="depth-banner-error">{patternError}</p> : null}
                  {patternResult ? (
                    <div className="depth-pattern-result">
                      <h3 className="depth-inline-title">
                        Pattern match ({patternResult.patterns_checked} checked)
                      </h3>
                      {(patternResult.matches || []).length === 0 ? (
                        <p className="depth-muted">{patternResult.no_match_reason}</p>
                      ) : (
                        <ul className="depth-match-list">
                          {patternResult.matches.map((m) => (
                            <li key={m.pattern_id} className="depth-match-item">
                              <div className="depth-match-head">
                                <code>{m.pattern_id}</code>
                                <TierBadge tier={m.confidence_tier} />
                              </div>
                              <ul className="depth-criteria">
                                {(m.criteria_met || []).map((c) => (
                                  <li key={c}>{c}</li>
                                ))}
                              </ul>
                              <button
                                type="button"
                                className="depth-btn depth-btn-secondary"
                                onClick={() =>
                                  setOpenDispute(openDispute === m.pattern_id ? null : m.pattern_id)
                                }
                              >
                                Dispute this
                              </button>
                              {openDispute === m.pattern_id ? (
                                <DisputePanel
                                  patternId={m.pattern_id}
                                  onClose={() => setOpenDispute(null)}
                                />
                              ) : null}
                            </li>
                          ))}
                        </ul>
                      )}
                    </div>
                  ) : null}
                </div>
              ) : null}

            </LayerCard>
          );
        })}
      </div>
    </div>
  );
}
