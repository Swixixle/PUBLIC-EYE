import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { getApiBase } from "../apiBase.js";
import { actorLedgerResolved, actorSlugCandidates } from "../utils/actorSlug.js";
import AccordionSection from "./AccordionSection.jsx";
import RabbitNudge from "./RabbitNudge.jsx";

const API = getApiBase();

async function fetchActorInLedger(slug) {
  const res = await fetch(`${API}/v1/actor/${encodeURIComponent(slug)}`);
  return res.ok;
}

/** Verbatim opening copy under ## Tone & Voice in `docs/RABBIT_HOLE_CONTEXT.md`. */
const OPENING_DISCLAIMER =
  "Rabbit Hole shows what the cited record states and what it does not state. It does not issue verdicts, moral judgments, or recommendations about what you should do or believe. Every surfaced line ties to a source id or to an explicit unknown; if something is missing from the record, the interface says so. This is a navigational map of public material at retrieval time, not legal advice, medical advice, personal advice, or proof of anyone's intent.";

const LAYER_CONFIG = [
  { id: 1, label: "Surface", color: "#4a9eff" },
  { id: 2, label: "Spread", color: "#9b59b6" },
  { id: 3, label: "Origin", color: "#e67e22" },
  { id: 4, label: "Actor", color: "#1abc9c" },
  { id: 5, label: "Pattern", color: "#e91e8c" },
  { id: 6, label: "X-border", color: "#64748b", sealed: true },
];

const GAP_EXPLANATIONS = {
  first_instance_indicators:
    "The earliest known appearance of this claim — where it first showed up publicly",
  seeding_actors:
    "Who originally introduced or amplified this narrative into public circulation",
  temporal_anchor: "A specific, verifiable date tied to the origin of this claim",
  platforms_mentioned: "Social platforms or channels where this story was shared or amplified",
  spread_indicators: "Language suggesting rapid, coordinated, or viral sharing patterns",
  ledger_matches:
    "Direct matches in the curated actor ledger — named entities with verified records",
  extracted_candidates:
    "Named people and organizations the actor layer tried to identify — none found",
  actors_not_in_ledger: "Entities mentioned that could not be resolved in the actor ledger",
  datable_sourceable_first_instance:
    "A first appearance that can be independently verified with a source and date",
  source_url: "A direct link to the primary source document",
  source_url_confidence_tier: "How reliable the primary source link is",
  what: "A factual description of what this narrative is about",
  when: "When this event or claim originated",
};

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

/** Map claim implication_risk to a spec tier for badge colors */
function implicationToTier(risk) {
  const r = String(risk || "low").toLowerCase();
  if (r === "high") return "cross_corroborated";
  if (r === "medium") return "single_source";
  return "structural_heuristic";
}

const DEPTH_CONFIDENCE_TIERS = new Set([
  "official_primary",
  "official_secondary",
  "aggregated_registry",
  "cross_corroborated",
  "single_source",
  "structural_heuristic",
]);

/** Media rows may use implication_risk (low/medium/high) or a literal ConfidenceTier (e.g. AssemblyAI mapping). */
function mediaClaimBadgeTier(claim) {
  const t = claim?.confidence_tier;
  const s = t != null ? String(t) : "";
  if (s && DEPTH_CONFIDENCE_TIERS.has(s)) return s;
  return implicationToTier(t);
}

const SKIP_ENTITY_PATTERNS = [
  /\(city[,)]/i,
  /\(district[,)]/i,
  /\(neighbourhood[,)]/i,
  /\(borough[,)]/i,
  /\(village[,)]/i,
  /\(town[,)]/i,
  /\(province[,)]/i,
  /\(region[,)]/i,
  /\(nation[,)]/i,
  /\(country[,)]/i,
  /\(oil tanker[,)]/i,
  /\(vessel[,)]/i,
  /\(ship[,)]/i,
  /\(waterway[,)]/i,
  /\(body of water[,)]/i,
  /\(strategic waterway[,)]/i,
  /\(facility[,)]/i,
  /\(building[,)]/i,
  /\(port[,)]/i,
  /\(airport[,)]/i,
  /\(strait[,)]/i,
  /\(bay[,)]/i,
  /\(sea[,)]/i,
  /\(ocean[,)]/i,
  /\(river[,)]/i,
  /\(lake[,)]/i,
];

function entityWorthLookup(name) {
  if (!name) return false;
  if (SKIP_ENTITY_PATTERNS.some((p) => p.test(name))) return false;
  const words = name.trim().split(/\s+/);
  if (words.length === 1 && name.length < 4) return false;
  return true;
}

/** Natural-language question / request (not a URL; skips short keyword-only traces). */
function isNaturalLanguageQuery(text) {
  const t = (text ?? "").trim();
  if (!t) return false;
  if (t.startsWith("http")) return false;
  const words = t.split(/\s+/);
  if (words.length < 3) return false;
  const lower = t.toLowerCase();
  const queryTriggers = [
    "tell",
    "what",
    "how",
    "why",
    "who",
    "where",
    "when",
    "explain",
    "show",
    "find",
    "search",
    "happening",
    "going",
    "latest",
    "recent",
    "today",
    "now",
    "is there",
    "are there",
    "give me",
    "summarize",
    "describe",
    "about",
  ];
  return queryTriggers.some((trigger) => lower.includes(trigger));
}

const ECOSYSTEM_ACCENT = {
  western_anglophone: "#4a9eff",
  russian_state: "#e05252",
  iranian_regional: "#2ecc71",
  chinese_state: "#e74c3c",
  arab_gulf: "#f39c12",
  israeli: "#9b59b6",
  south_asian: "#1abc9c",
  european: "#3498db",
};

function GlobalPerspectivesPanel({ result }) {
  const [expanded, setExpanded] = useState({});

  if (!result || typeof result !== "object") return null;

  const ecosystems = result.ecosystems || [];
  const divergence = result.divergence_points || [];
  const consensus = result.consensus_elements || [];
  const absent = result.absent_from_all || [];
  const mostDivergent = result.most_divergent_pair;

  function toggle(id) {
    setExpanded((p) => ({ ...p, [id]: !p[id] }));
  }

  return (
    <div className="depth-global-perspectives">
      <h3 className="depth-inline-title">Global perspectives</h3>
      {result.error ? <p className="depth-banner-error">{result.error}</p> : null}
      {result.claim ? <p className="depth-gp-claim">&quot;{result.claim}&quot;</p> : null}
      {(result.confidence_note || !result.error) ? (
        <p className="depth-muted depth-gp-note" style={{ fontSize: "11px", marginBottom: "14px" }}>
          {result.confidence_note ||
            "Framing analysis is model-informed; verify against live sources before citing."}
        </p>
      ) : null}

      {mostDivergent ? (
        <div className="depth-gp-divergent-pair">
          <span className="depth-gp-divergent-label">Most irreconcilable:</span>{" "}
          {mostDivergent.ecosystem_a} vs {mostDivergent.ecosystem_b}
          {mostDivergent.reason ? (
            <span className="depth-gp-divergent-reason"> — {mostDivergent.reason}</span>
          ) : null}
        </div>
      ) : null}

      <div className="depth-gp-ecosystems">
        {ecosystems.map((eco) => {
          const accent = ECOSYSTEM_ACCENT[eco.id] || "#888";
          const isOpen = expanded[eco.id];
          return (
            <div key={eco.id} className="depth-gp-ecosystem" style={{ borderLeftColor: accent }}>
              <button
                type="button"
                className="depth-gp-ecosystem-head"
                onClick={() => toggle(eco.id)}
              >
                <span className="depth-gp-ecosystem-label">{eco.label}</span>
                <span className="depth-gp-outlets">{(eco.outlets || []).join(", ")}</span>
                <span className="depth-gp-chevron">{isOpen ? "▼" : "▶"}</span>
              </button>

              <p className="depth-gp-framing">{eco.framing}</p>

              {isOpen ? (
                <div className="depth-gp-detail">
                  {eco.key_language?.length > 0 ? (
                    <div className="depth-gp-keywords">
                      {eco.key_language.map((w, i) => (
                        <code key={i} className="depth-gp-keyword">
                          {w}
                        </code>
                      ))}
                    </div>
                  ) : null}
                  {eco.emphasized ? (
                    <div className="depth-gp-row">
                      <span className="depth-gp-row-label">Emphasizes</span>
                      <span>{eco.emphasized}</span>
                    </div>
                  ) : null}
                  {eco.minimized ? (
                    <div className="depth-gp-row">
                      <span className="depth-gp-row-label">Minimizes</span>
                      <span className="depth-muted">{eco.minimized}</span>
                    </div>
                  ) : null}
                  {eco.confidence_note ? (
                    <div className="depth-gp-row">
                      <span className="depth-gp-row-label">Confidence</span>
                      <span className="depth-muted" style={{ fontSize: "11px" }}>
                        {eco.confidence_note}
                      </span>
                    </div>
                  ) : null}
                </div>
              ) : null}
            </div>
          );
        })}
      </div>

      {divergence.length > 0 ? (
        <div className="depth-gp-section">
          <strong className="depth-gp-section-title">Where framings conflict</strong>
          <ul className="depth-gp-list">
            {divergence.map((d, i) => (
              <li key={i}>{d}</li>
            ))}
          </ul>
        </div>
      ) : null}

      {consensus.length > 0 ? (
        <div className="depth-gp-section">
          <strong className="depth-gp-section-title">What all agree on</strong>
          <ul className="depth-gp-list depth-gp-list-consensus">
            {consensus.map((c, i) => (
              <li key={i}>{c}</li>
            ))}
          </ul>
        </div>
      ) : null}

      {absent.length > 0 ? (
        <div className="depth-gp-section">
          <strong className="depth-gp-section-title">What nobody is covering</strong>
          <ul className="depth-gp-list depth-gp-list-absent">
            {absent.map((a, i) => (
              <li key={i}>{a}</li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}

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

function GapChips({ fields, showHeader = true }) {
  const [tooltip, setTooltip] = useState(null);
  if (!fields || fields.length === 0) return null;
  return (
    <div className={`depth-gap-chips ${showHeader ? "" : "depth-gap-chips--no-header"}`}>
      {showHeader ? (
        <span className="depth-gap-label">
          <span className="depth-gap-icon">⊘</span> Missing
        </span>
      ) : null}
      <div className="depth-gap-chip-row">
        {fields.map((f) => (
          <button
            key={f}
            type="button"
            className="depth-gap-chip"
            onClick={() => setTooltip(tooltip === f ? null : f)}
            title={GAP_EXPLANATIONS[f] || f}
          >
            {f.replace(/_/g, " ")}
            {tooltip === f ? (
              <span className="depth-gap-tooltip">{GAP_EXPLANATIONS[f] || "No explanation available"}</span>
            ) : null}
          </button>
        ))}
      </div>
    </div>
  );
}

function DepthCard({ title, tier, children, isEmpty }) {
  return (
    <div className={`depth-card ${isEmpty ? "depth-card-empty" : ""}`}>
      <div className="depth-card-header">
        <span className="depth-card-title">{title}</span>
        {tier ? <TierBadge tier={tier} /> : null}
      </div>
      <div className="depth-card-body">{children}</div>
    </div>
  );
}

function LayerTabBar({ activeLayer, onSelect, layerStates }) {
  return (
    <div className="depth-tab-bar" role="navigation" aria-label="Depth layers">
      {LAYER_CONFIG.map((layer) => {
        const state = layerStates[layer.id] || "idle";
        const isActive = activeLayer === layer.id;
        const hasData = state === "found";
        const isEmpty = state === "empty";
        const isSealed = Boolean(layer.sealed);
        return (
          <button
            key={layer.id}
            type="button"
            className={[
              "depth-tab",
              isActive ? "depth-tab--active" : "",
              hasData ? "depth-tab--has-data" : "",
              isEmpty ? "depth-tab--empty" : "",
              isSealed ? "depth-tab--sealed" : "",
            ]
              .filter(Boolean)
              .join(" ")}
            style={{ "--tab-color": layer.color }}
            onClick={() => !isSealed && onSelect(layer.id)}
            disabled={isSealed}
            title={isSealed ? "Adapter not yet built" : layer.label}
          >
            <span className="depth-tab-num">{layer.id}</span>
            <span className="depth-tab-label">{layer.label}</span>
            {hasData ? <span className="depth-tab-dot" /> : null}
            {isSealed ? <span className="depth-tab-lock">🔒</span> : null}
          </button>
        );
      })}
    </div>
  );
}

function TimelineSynthesisPanel({ synthesis, timelineGroups, dateRangeLabel }) {
  const hasSynth = synthesis && typeof synthesis === "object";
  const hasGroups = Array.isArray(timelineGroups) && timelineGroups.length > 0;
  if (!hasSynth && !hasGroups) return null;

  return (
    <div className="depth-timeline-synthesis">
      {hasSynth && synthesis.arc ? (
        <div className="depth-query-what">
          <div
            style={{
              fontSize: "11px",
              color: "var(--muted,#888)",
              marginBottom: "6px",
              textTransform: "uppercase",
              letterSpacing: ".06em",
            }}
          >
            {dateRangeLabel || synthesis.period || "Period"} — arc
          </div>
          <p>{synthesis.arc}</p>
          {synthesis.confidence_tier ? <TierBadge tier={synthesis.confidence_tier} /> : null}
        </div>
      ) : null}

      {hasSynth && synthesis.error ? (
        <p className="depth-banner-error">{synthesis.error}</p>
      ) : null}

      {hasSynth && (synthesis.key_moments || []).length > 0 ? (
        <div className="depth-query-section">
          <strong className="depth-query-section-title">Key moments</strong>
          <ul className="depth-query-timeline">
            {synthesis.key_moments.map((m, i) => (
              <li key={i}>
                <span className="depth-query-timeline-when">{m.when}</span>
                <span className="depth-query-timeline-event">{m.what}</span>
                {(m.outlets || []).length > 0 ? (
                  <span className="depth-query-timeline-source">{m.outlets.join(", ")}</span>
                ) : null}
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {hasSynth && (synthesis.consistent_elements || []).length > 0 ? (
        <div className="depth-query-section">
          <strong className="depth-query-section-title">What stayed consistent</strong>
          <ul className="depth-query-list">
            {synthesis.consistent_elements.map((w, i) => (
              <li key={i}>{w}</li>
            ))}
          </ul>
        </div>
      ) : null}

      {hasSynth && (synthesis.what_changed || []).length > 0 ? (
        <div className="depth-query-section">
          <strong className="depth-query-section-title">What changed</strong>
          <ul className="depth-query-list">
            {synthesis.what_changed.map((w, i) => (
              <li key={i}>{w}</li>
            ))}
          </ul>
        </div>
      ) : null}

      {hasSynth && synthesis.ecosystem_divergence ? (
        <div className="depth-query-section">
          <strong className="depth-query-section-title">How ecosystems diverged</strong>
          <p
            style={{
              fontSize: "13px",
              color: "var(--fg-secondary,#ccc)",
              lineHeight: 1.7,
            }}
          >
            {synthesis.ecosystem_divergence}
          </p>
        </div>
      ) : null}

      {hasGroups ? (
        <div className="depth-query-section">
          <strong className="depth-query-section-title">Coverage by week</strong>
          {timelineGroups.map((g, i) => (
            <div key={i} className="depth-timeline-week">
              <div className="depth-timeline-week-label">
                {g.week}
                <span className="depth-timeline-week-count">
                  {g.count} article{g.count !== 1 ? "s" : ""}
                </span>
              </div>
              <ul className="depth-timeline-week-articles">
                {(g.articles || []).slice(0, 3).map((a, j) => (
                  <li key={j}>
                    <a
                      href={a.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="depth-query-source-link"
                    >
                      {a.title || a.url}
                    </a>
                    <span className="depth-query-source-outlet">{a.outlet}</span>
                  </li>
                ))}
                {g.count > 3 ? (
                  <li className="depth-timeline-more">+{g.count - 3} more</li>
                ) : null}
              </ul>
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function QuerySynthesisPanel({ result }) {
  if (!result) return null;
  const isTimeline = result.query_type === "entity_timeline";
  const synthesis = result.synthesis || {};
  const timelineSynthesis = result.timeline_synthesis || {};
  const timelineGroups = result.timeline_groups || [];
  const articles = result.articles || [];
  const gp = result.global_perspectives || {};
  const classification = result.classification || {};
  const dateRangeLabel = classification.date_range?.label || "";

  return (
    <div className="depth-query-synthesis">
      <h2 className="depth-inline-title">
        {isTimeline ? "Coverage timeline" : "Query synthesis"}
      </h2>
      <p className="depth-muted" style={{ fontSize: "12px", marginBottom: "12px" }}>
        <code>{result.receipt_id}</code> · {result.generated_at} ·{" "}
        {result.signed ? "signed" : "unsigned"} ·{" "}
        {typeof result.sources_searched === "number"
          ? `${result.sources_searched} sources searched`
          : result.sources_searched}{" "}
        · {result.articles_found} articles found
        {dateRangeLabel ? ` · ${dateRangeLabel}` : ""}
      </p>

      {result.error ? <p className="depth-banner-error">{result.error}</p> : null}

      {isTimeline ? (
        <TimelineSynthesisPanel
          synthesis={timelineSynthesis}
          timelineGroups={timelineGroups}
          dateRangeLabel={dateRangeLabel}
        />
      ) : (
        <>
          {synthesis.error ? <p className="depth-banner-error">{synthesis.error}</p> : null}

          {synthesis.what_is_happening ? (
            <div className="depth-query-what">
              <p>{synthesis.what_is_happening}</p>
              {synthesis.confidence_tier ? <TierBadge tier={synthesis.confidence_tier} /> : null}
            </div>
          ) : null}

          {(synthesis.key_facts || []).length > 0 ? (
            <div className="depth-query-section">
              <strong className="depth-query-section-title">Confirmed across sources</strong>
              <ul className="depth-query-list">
                {synthesis.key_facts.map((f, i) => (
                  <li key={i}>
                    <span>{f.fact}</span>
                    <span className="depth-query-supported">{(f.supported_by || []).join(", ")}</span>
                  </li>
                ))}
              </ul>
            </div>
          ) : null}

          {(synthesis.contested_facts || []).length > 0 ? (
            <div className="depth-query-section">
              <strong className="depth-query-section-title">Contested between sources</strong>
              {synthesis.contested_facts.map((c, i) => (
                <div key={i} className="depth-query-contested">
                  <div className="depth-query-contested-fact">{c.fact}</div>
                  <div className="depth-query-contested-sides">
                    <div>
                      <span className="depth-query-outlet-list">{(c.outlets_a || []).join(", ")}</span>
                      <span>: {c.version_a}</span>
                    </div>
                    <div>
                      <span className="depth-query-outlet-list">{(c.outlets_b || []).join(", ")}</span>
                      <span>: {c.version_b}</span>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          ) : null}

          {(synthesis.what_nobody_is_saying || []).length > 0 ? (
            <div className="depth-query-section">
              <strong className="depth-query-section-title">What nobody is covering</strong>
              <ul className="depth-query-list depth-query-list-absent">
                {synthesis.what_nobody_is_saying.map((w, i) => (
                  <li key={i}>{w}</li>
                ))}
              </ul>
            </div>
          ) : null}

          {(synthesis.timeline || []).length > 0 ? (
            <div className="depth-query-section">
              <strong className="depth-query-section-title">Timeline</strong>
              <ul className="depth-query-timeline">
                {synthesis.timeline.map((t, i) => (
                  <li key={i}>
                    <span className="depth-query-timeline-when">{t.when}</span>
                    <span className="depth-query-timeline-event">{t.event}</span>
                    {t.source ? (
                      <span className="depth-query-timeline-source">{t.source}</span>
                    ) : null}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
        </>
      )}

      {articles.length > 0 ? (
        <div className="depth-query-section">
          <strong className="depth-query-section-title">Sources</strong>
          <ul className="depth-query-sources">
            {articles.map((a, i) => (
              <li key={i}>
                <a
                  href={a.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="depth-query-source-link"
                >
                  {a.title || a.url}
                </a>
                <span className="depth-query-source-outlet">{a.outlet}</span>
                {a.source === "gdelt" ? (
                  <span className="depth-query-gdelt-badge">GDELT</span>
                ) : null}
                {!a.fetch_success ? (
                  <span className="depth-query-fetch-fail">(summary only)</span>
                ) : null}
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {gp && (gp.ecosystems || []).length > 0 ? (
        <div className="depth-query-section">
          <GlobalPerspectivesPanel result={gp} />
        </div>
      ) : null}
    </div>
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

const WHO_OBJECT_PATTERNS = /vessel|ship|tanker|aircraft|satellite|facility|building|plant/i;
const WHO_STATE_PATTERNS =
  /nation|country|government|ministry|agency|department|bureau|court|congress|senate|committee|union|organization|institution|university|company|corp|inc\.|llc/i;

function groupWho(whoList) {
  const people = [];
  const statesInstitutions = [];
  const objects = [];
  const other = [];
  for (const w of whoList) {
    const name = w.name || "";
    if (WHO_OBJECT_PATTERNS.test(name)) {
      objects.push(w);
    } else if (
      WHO_STATE_PATTERNS.test(name) ||
      /\(nation|country|state/i.test(name)
    ) {
      statesInstitutions.push(w);
    } else if (/^[A-Z][a-z]+ [A-Z]/.test(name) && !/\(/.test(name)) {
      people.push(w);
    } else {
      other.push(w);
    }
  }
  return { people, statesInstitutions, objects, other };
}

function WhoGroup({ label, entities, ledgerPresence, actorDepthByEntity, actorDepthLoading, onActorDepth }) {
  if (!entities || entities.length === 0) return null;
  return (
    <div className="depth-who-group">
      <div className="depth-who-group-label">{label}</div>
      {entities.map((w) => {
        const { checked, resolvedSlug, inLedger } = actorLedgerResolved(w.name, ledgerPresence);
        const showRabbit = entityWorthLookup(w.name);
        return (
          <div key={w.name} className="depth-who-card">
            <div className="depth-who-card-main">
              <span className="depth-who-card-name">{w.name}</span>
              <TierBadge tier={w.confidence_tier} />
            </div>
            {!checked ? (
              <span className="depth-muted rabbit-nudge-pending" title="Checking ledger…">
                …
              </span>
            ) : showRabbit ? (
              <ActorDepthTrigger
                entityName={w.name}
                ledgerHref={
                  inLedger ? `${API}/v1/actor/${encodeURIComponent(resolvedSlug)}` : null
                }
                result={actorDepthByEntity[w.name]}
                loading={actorDepthLoading[w.name]}
                onLookup={onActorDepth}
              />
            ) : null}
          </div>
        );
      })}
    </div>
  );
}

function SurfaceTraceFields({
  trace,
  ledgerPresence,
  onActorDepth,
  actorDepthByEntity,
  actorDepthLoading,
  omitWhatForUrl,
}) {
  const sorted = [...(trace.who || [])].sort((a, b) =>
    String(a.name || "").toLowerCase().localeCompare(String(b.name || "").toLowerCase()),
  );
  const groups = groupWho(sorted);
  const whoEmpty =
    !groups.people.length &&
    !groups.statesInstitutions.length &&
    !groups.objects.length &&
    !groups.other.length;
  return (
    <>
      {omitWhatForUrl ? null : (
        <DepthCard title="What" tier={trace.what_confidence_tier} isEmpty={!trace.what}>
          <p className="depth-what">{trace.what}</p>
          {trace.cultural_substrate ? (
            <p className="depth-cultural-substrate">{trace.cultural_substrate}</p>
          ) : null}
        </DepthCard>
      )}
      {trace.cultural_substrate && omitWhatForUrl ? (
        <DepthCard title="Cultural substrate" isEmpty={false}>
          <p className="depth-cultural-substrate">{trace.cultural_substrate}</p>
        </DepthCard>
      ) : null}
      <DepthCard title="Who" isEmpty={whoEmpty}>
        <div className="depth-who">
          <strong>Who</strong>
          <WhoGroup
            label="People"
            entities={groups.people}
            ledgerPresence={ledgerPresence}
            actorDepthByEntity={actorDepthByEntity}
            actorDepthLoading={actorDepthLoading}
            onActorDepth={onActorDepth}
          />
          <WhoGroup
            label="States & institutions"
            entities={groups.statesInstitutions}
            ledgerPresence={ledgerPresence}
            actorDepthByEntity={actorDepthByEntity}
            actorDepthLoading={actorDepthLoading}
            onActorDepth={onActorDepth}
          />
          <WhoGroup
            label="Vessels & objects"
            entities={groups.objects}
            ledgerPresence={ledgerPresence}
            actorDepthByEntity={actorDepthByEntity}
            actorDepthLoading={actorDepthLoading}
            onActorDepth={onActorDepth}
          />
          <WhoGroup
            label="Other"
            entities={groups.other}
            ledgerPresence={ledgerPresence}
            actorDepthByEntity={actorDepthByEntity}
            actorDepthLoading={actorDepthLoading}
            onActorDepth={onActorDepth}
          />
        </div>
      </DepthCard>
      <DepthCard
        title="When"
        tier={trace.when?.confidence_tier}
        isEmpty={!trace.when?.earliest_appearance}
      >
        {trace.when ? (
          <div className="depth-when-block">
            <strong>When</strong>
            <div className="depth-when-primary">{trace.when.earliest_appearance}</div>
            {trace.when.source ? (
              <div className="depth-when-source">{trace.when.source}</div>
            ) : null}
            {trace.when.confidence_tier ? (
              <TierBadge tier={trace.when.confidence_tier} />
            ) : null}
          </div>
        ) : null}
      </DepthCard>
      <GapChips fields={trace.absent_fields} />
    </>
  );
}

function OriginResultFields({ origin }) {
  if (!origin || typeof origin !== "object") return null;
  const indicators = origin.first_instance_indicators || [];
  const actors = origin.seeding_actors || [];
  const absent = origin.absent_fields || [];
  const hasSignals =
    Boolean(origin.anchor_description) || indicators.length > 0 || actors.length > 0;
  return (
    <div className="depth-origin-result">
      <div className="depth-origin-head depth-meta-row depth-spread-meta">
        <span className="depth-muted">
          Anchor (heuristic): {origin.anchor_exists ? "yes" : "no"}
        </span>
        {origin.confidence_tier ? <TierBadge tier={origin.confidence_tier} /> : null}
      </div>
      {hasSignals ? (
        <div className="depth-signals-found">
          <div className="depth-signals-label">Signals found</div>
          {origin.anchor_description ? (
            <p className="depth-origin-anchor">{origin.anchor_description}</p>
          ) : null}
          {indicators.length > 0 ? (
            <div className="depth-spread-block">
              <strong>First-instance language</strong>
              <ul className="depth-spread-list">
                {indicators.map((x) => (
                  <li key={x}>{x}</li>
                ))}
              </ul>
            </div>
          ) : null}
          {actors.length > 0 ? (
            <div className="depth-spread-block">
              <strong>Seeding actors (heuristic)</strong>
              <ul className="depth-spread-list">
                {actors.map((a) => (
                  <li key={a}>{a}</li>
                ))}
              </ul>
            </div>
          ) : null}
        </div>
      ) : null}
      {absent.length > 0 ? (
        <div className="depth-signals-missing">
          <div className="depth-signals-label depth-signals-label--missing">Signals missing</div>
          <GapChips fields={absent} showHeader={false} />
        </div>
      ) : null}
    </div>
  );
}

function normalizeActorLookupSources(src) {
  if (src == null) return [];
  if (Array.isArray(src)) return src.filter(Boolean);
  return [src];
}

/** Deep link: first match wikidata → wikipedia → ledger API. */
function actorLayerDeepHref(a) {
  const sources = normalizeActorLookupSources(a.lookup_source);
  if (sources.includes("wikidata") && a.wikidata_id) {
    return `https://www.wikidata.org/wiki/${encodeURIComponent(a.wikidata_id)}`;
  }
  if (sources.includes("wikipedia") && a.wikipedia_title) {
    return `https://en.wikipedia.org/wiki/${encodeURIComponent(a.wikipedia_title)}`;
  }
  return `${API}/v1/actor/${encodeURIComponent(a.slug)}`;
}

/** Inline panel: matches `ActorLayerResult` / `ActorRecord` from `POST /v1/actor-layer`. */
function ActorDepthResultBody({ data }) {
  if (!data || typeof data !== "object" || data.error) return null;
  const found = data.actors_found || [];
  const absent = data.actors_absent || [];
  const checks = [...(data.sources_checked || [])].sort((a, b) =>
    String(a.adapter).localeCompare(String(b.adapter)),
  );
  return (
    <div className="actor-depth-result">
      {checks.length > 0 ? (
        <div className="actor-depth-sources-checked">
          {checks.map((s, k) => (
            <span key={`${s.adapter}-${k}`} className={`source-badge status-${s.status}`}>
              {s.adapter}
            </span>
          ))}
        </div>
      ) : null}
      {data.confidence_tier ? (
        <div className="depth-meta-row actor-depth-tier">
          <TierBadge tier={data.confidence_tier} />
          <span className="depth-muted">on-demand Layer 4</span>
        </div>
      ) : null}
      {found.length > 0 ? (
        found.map((actor, i) => {
          const deepHref = actorLayerDeepHref(actor);
          const wd = actor.wikidata_id
            ? `https://www.wikidata.org/wiki/${encodeURIComponent(actor.wikidata_id)}`
            : null;
          const wp = actor.wikipedia_title
            ? `https://en.wikipedia.org/wiki/${encodeURIComponent(String(actor.wikipedia_title).replace(/ /g, "_"))}`
            : null;
          return (
            <div key={actor.slug || `a-${i}`} className="actor-record">
              {actor.name ? <div className="actor-name">{actor.name}</div> : null}
              {actor.slug ? (
                <code className="depth-actor-slug actor-slug-inline">{actor.slug}</code>
              ) : null}
              <div className="actor-depth-link-row">
                {deepHref ? (
                  <a
                    href={deepHref}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="actor-link"
                  >
                    Primary record →
                  </a>
                ) : null}
                {wd ? (
                  <a href={wd} target="_blank" rel="noopener noreferrer" className="actor-link">
                    Wikidata →
                  </a>
                ) : null}
                {wp ? (
                  <a href={wp} target="_blank" rel="noopener noreferrer" className="actor-link">
                    Wikipedia →
                  </a>
                ) : null}
                {actor.slug ? (
                  <a
                    href={`${API}/v1/actor/${encodeURIComponent(actor.slug)}`}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="actor-link"
                  >
                    Ledger API →
                  </a>
                ) : null}
              </div>
              {(actor.aliases || []).length > 0 ? (
                <div className="actor-aliases-block">
                  <strong className="actor-aliases-label">Aliases</strong>
                  <ul className="depth-spread-list actor-aliases-list">
                    {(actor.aliases || []).map((al) => (
                      <li key={al}>{al}</li>
                    ))}
                  </ul>
                </div>
              ) : null}
              {(actor.events || []).length > 0 ? (
                <ul className="actor-events-compact">
                  {(actor.events || []).map((ev, j) => {
                    const src = String(ev.source || "").trim();
                    const srcIsUrl = /^https?:\/\//i.test(src);
                    return (
                      <li key={`${ev.date}-${j}`}>
                        <span className="depth-actor-ev-date">{ev.date}</span>{" "}
                        <span className="depth-muted">{ev.type}</span>
                        {ev.confidence_tier ? <TierBadge tier={ev.confidence_tier} /> : null}
                        <p className="depth-actor-ev-desc">{ev.description}</p>
                        {src ? (
                          <p className="depth-muted depth-actor-ev-src">
                            {srcIsUrl ? (
                              <a href={src} target="_blank" rel="noopener noreferrer" className="actor-link">
                                Source link →
                              </a>
                            ) : (
                              src
                            )}
                          </p>
                        ) : null}
                      </li>
                    );
                  })}
                </ul>
              ) : (
                <p className="depth-muted actor-no-events-note">No timeline events in this row.</p>
              )}
            </div>
          );
        })
      ) : (
        <div className="actor-not-found">
          No actor record returned for this lookup (narrative may be too short to qualify for dynamic
          resolution).
          {absent.length > 0 ? (
            <ul className="depth-spread-list actor-absent-inline-list">
              {absent.map((x) => (
                <li key={x.name}>
                  {x.name}
                  {x.wikidata_attempted ? (
                    <span className="depth-muted"> — dynamic chain ran, no match</span>
                  ) : (
                    <span className="depth-muted"> — skipped or below relevance filter</span>
                  )}
                </li>
              ))}
            </ul>
          ) : null}
          <span className="actor-absent-note">Absence and adapter status are reflected in badges above.</span>
        </div>
      )}
    </div>
  );
}

function ActorDepthTrigger({ entityName, ledgerHref, result, loading, onLookup }) {
  const errMsg = result && result.error ? result.error : null;
  const payload = result && !result.error ? result : null;
  return (
    <div className="actor-depth-trigger-wrap">
      <span className="actor-depth-trigger-row">
        <button
          type="button"
          className="rabbit-nudge rabbit-nudge--action"
          onClick={() => onLookup(entityName)}
          disabled={!!loading}
          title="Run full Layer 4 lookup: ledger, Wikidata, Wikipedia, archives"
        >
          <span className="rabbit-nudge-emoji" aria-hidden="true">
            🐇
          </span>
        </button>
        {ledgerHref ? (
          <a
            href={ledgerHref}
            className="actor-ledger-quick-link"
            target="_blank"
            rel="noopener noreferrer"
            title="Open actor ledger record"
          >
            Ledger
          </a>
        ) : null}
      </span>
      {loading ? <span className="actor-loading">Looking up public records…</span> : null}
      {errMsg ? <div className="actor-depth-result actor-depth-error">{errMsg}</div> : null}
      {payload ? <ActorDepthResultBody data={payload} /> : null}
    </div>
  );
}

const ACTOR_SOURCE_BADGE_ORDER = [
  "ledger",
  "web_inference",
  "internet_archive",
  "chronicling_america",
  "jstor",
  "mysterious_universe",
  "anomalist",
  "cryptomundo",
  "coast_to_coast",
  "singular_fortean",
  "fortean_times",
];

const ACTOR_EVENT_CATEGORY_LABEL = {
  primary_historical: "Primary historical",
  academic: "Academic",
  news_archive: "News archive",
  paranormal_community: "Paranormal / community",
  dynamic_inference: "Dynamic inference",
};

/** @param {Array<Record<string, unknown>>} events */
function groupActorEventsByCategory(events) {
  const CATEGORY_ORDER = [
    "primary_historical",
    "news_archive",
    "academic",
    "paranormal_community",
    "dynamic_inference",
  ];
  const groups = new Map();
  for (const ev of events || []) {
    const raw = ev.source_category;
    const key = raw && typeof raw === "string" ? raw : "_other";
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(ev);
  }
  const sortedKeys = [...groups.keys()].sort((a, b) => {
    const rank = (k) => {
      if (k === "_other") return 999;
      const i = CATEGORY_ORDER.indexOf(k);
      return i === -1 ? 998 : i;
    };
    return rank(a) - rank(b);
  });
  return sortedKeys.map((k) => ({
    key: k,
    label:
      k === "_other"
        ? "Other sources"
        : ACTOR_EVENT_CATEGORY_LABEL[k] || String(k).replace(/_/g, " "),
    items: groups.get(k),
  }));
}

function singleActorSourceBadge(source) {
  if (source === "ledger") {
    return (
      <span key="ledger" className="depth-actor-source-badge depth-actor-source-ledger">
        LEDGER
      </span>
    );
  }
  if (source === "web_inference") {
    return (
      <span key="web_inference" className="depth-actor-source-badge depth-actor-source-web">
        WEB — UNVERIFIED
      </span>
    );
  }
  if (source === "internet_archive") {
    return (
      <span key="internet_archive" className="depth-actor-source-badge depth-actor-source-ia">
        INTERNET ARCHIVE
      </span>
    );
  }
  if (source === "chronicling_america") {
    return (
      <span key="chronicling_america" className="depth-actor-source-badge depth-actor-source-ca">
        CHRONICLING AMERICA
      </span>
    );
  }
  if (source === "jstor") {
    return (
      <span key="jstor" className="depth-actor-source-badge depth-actor-source-jstor">
        JSTOR
      </span>
    );
  }
  if (source === "mysterious_universe") {
    return (
      <span key="mysterious_universe" className="depth-actor-source-badge depth-actor-source-mu">
        MYSTERIOUS UNIVERSE
      </span>
    );
  }
  if (source === "anomalist") {
    return (
      <span key="anomalist" className="depth-actor-source-badge depth-actor-source-anom">
        ANOMALIST
      </span>
    );
  }
  if (source === "cryptomundo") {
    return (
      <span key="cryptomundo" className="depth-actor-source-badge depth-actor-source-crypto">
        CRYPTOMUNDO
      </span>
    );
  }
  if (source === "coast_to_coast") {
    return (
      <span key="coast_to_coast" className="depth-actor-source-badge depth-actor-source-c2c">
        COAST TO COAST
      </span>
    );
  }
  if (source === "singular_fortean") {
    return (
      <span key="singular_fortean" className="depth-actor-source-badge depth-actor-source-sfs">
        SINGULAR FORTEAN
      </span>
    );
  }
  if (source === "fortean_times") {
    return (
      <span key="fortean_times" className="depth-actor-source-badge depth-actor-source-ft">
        FORTEAN TIMES
      </span>
    );
  }
  return null;
}

function PrimarySourceChips({ events }) {
  const rows = (events || []).filter(
    (e) =>
      e &&
      e.type !== "layer1_trace" &&
      (e.source_category === "primary_historical" ||
        e.source_category === "academic" ||
        e.source_category === "news_archive" ||
        e.type === "wikipedia_reference_url" ||
        e.type === "wikidata_reference_url"),
  );
  if (rows.length === 0) return null;
  return (
    <span className="depth-actor-primary-chips">
      {rows.slice(0, 8).map((e, i) => (
        <span key={`${e.source}-${e.date}-${i}`} className="depth-actor-primary-chip" title={e.source}>
          {(e.description || e.source || "").slice(0, 72)}
        </span>
      ))}
    </span>
  );
}

function ActorLookupSourceBadge({ lookup_source: src }) {
  const raw = normalizeActorLookupSources(src).filter(
    (s) => s && s !== "wikidata" && s !== "wikipedia",
  );
  if (raw.length === 0) return null;
  const rank = (x) => {
    const i = ACTOR_SOURCE_BADGE_ORDER.indexOf(x);
    return i === -1 ? 999 : i;
  };
  const sorted = [...raw].sort((a, b) => rank(a) - rank(b));
  return (
    <span className="depth-actor-source-badges">
      {sorted.map((s) => singleActorSourceBadge(s)).filter(Boolean)}
    </span>
  );
}

function ActorLayerFields({ actorLayer, onActorDepth, actorDepthByEntity, actorDepthLoading }) {
  if (!actorLayer || typeof actorLayer !== "object") return null;
  const found = actorLayer.actors_found || [];
  const absent = actorLayer.actors_absent || [];
  const gaps = actorLayer.absent_fields || [];
  const dynamicLookups = actorLayer.dynamic_lookups ?? 0;
  const hasBody = found.length > 0 || absent.length > 0;
  const hasMissingBlock = absent.length > 0 || gaps.length > 0 || !hasBody;
  return (
    <div className="depth-actor-layer-result">
      <div className="depth-meta-row depth-spread-meta">
        {actorLayer.confidence_tier ? <TierBadge tier={actorLayer.confidence_tier} /> : null}
        {dynamicLookups > 0 ? (
          <span className="depth-muted" title="Resolved via Wikidata / Wikipedia / web inference">
            Dynamic: {dynamicLookups}
          </span>
        ) : (
          <span className="depth-muted">Ledger resolution</span>
        )}
      </div>
      {found.length > 0 ? (
        <div className="depth-signals-found">
          <div className="depth-signals-label">Signals found</div>
          <ul className="depth-actor-found-list">
            {found.map((a) => {
              const deepHref = actorLayerDeepHref(a);
              return (
                <li key={a.slug} className="depth-actor-card">
                  <div className="depth-actor-head">
                    <strong>{a.name}</strong>
                    <ActorLookupSourceBadge lookup_source={a.lookup_source} />
                    <PrimarySourceChips events={a.events} />
                    <code className="depth-actor-slug">{a.slug}</code>
                    <RabbitNudge href={deepHref} absent={!deepHref} label="deeper" />
                  </div>
                  {a.what || a.cultural_substrate || (a.surface_who && a.surface_who.length > 0) || a.surface_when ? (
                    <div className="depth-actor-layer1-trace">
                      <h4 className="depth-actor-layer1-title">Entity trace (Layer 1)</h4>
                      {a.what ? <p className="depth-actor-layer1-what">{a.what}</p> : null}
                      {a.cultural_substrate ? (
                        <p className="depth-actor-layer1-substrate">{a.cultural_substrate}</p>
                      ) : null}
                      {a.what_confidence_tier ? (
                        <div className="depth-meta-row">
                          <TierBadge tier={a.what_confidence_tier} />
                          <span className="depth-muted">what tier (surface)</span>
                        </div>
                      ) : null}
                      {a.surface_who && a.surface_who.length > 0 ? (
                        <div className="depth-spread-block">
                          <strong>Who</strong>
                          <ul className="depth-spread-list">
                            {[...a.surface_who]
                              .sort((x, y) =>
                                String(x.name || "").toLowerCase().localeCompare(String(y.name || "").toLowerCase()),
                              )
                              .map((w) => (
                                <li key={w.name}>
                                  {w.name} <TierBadge tier={w.confidence_tier} />
                                </li>
                              ))}
                          </ul>
                        </div>
                      ) : null}
                      {a.surface_when && (a.surface_when.earliest_appearance || a.surface_when.source) ? (
                        <div className="depth-when depth-actor-layer1-when">
                          <strong>When</strong>
                          <p>{a.surface_when.earliest_appearance}</p>
                          <p className="depth-muted">{a.surface_when.source}</p>
                          <TierBadge tier={a.surface_when.confidence_tier} />
                        </div>
                      ) : null}
                    </div>
                  ) : null}
                  {(a.aliases || []).length > 0 ? (
                    <div className="depth-spread-block">
                      <strong>Aliases</strong>
                      <ul className="depth-spread-list">
                        {(a.aliases || []).map((al) => (
                          <li key={al}>{al}</li>
                        ))}
                      </ul>
                    </div>
                  ) : null}
                  {(a.events || []).length > 0 ? (
                    <div className="depth-spread-block">
                      <strong>Events</strong>
                      {groupActorEventsByCategory(a.events || []).map((grp) => (
                        <div key={grp.key} className="depth-actor-event-group">
                          <h4 className="depth-actor-event-group-title">{grp.label}</h4>
                          <ul className="depth-actor-events">
                            {grp.items.map((ev, i) => (
                              <li key={`${grp.key}-${ev.date}-${i}`}>
                                <span className="depth-actor-ev-date">{ev.date}</span>{" "}
                                <span className="depth-muted">{ev.type}</span>
                                <TierBadge tier={ev.confidence_tier} />
                                <p className="depth-actor-ev-desc">{ev.description}</p>
                                <p className="depth-muted depth-actor-ev-src">{ev.source}</p>
                              </li>
                            ))}
                          </ul>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <p className="depth-muted">No events on this ledger row.</p>
                  )}
                </li>
              );
            })}
          </ul>
        </div>
      ) : null}
      {hasMissingBlock ? (
        <div className="depth-signals-missing">
          <div className="depth-signals-label depth-signals-label--missing">Signals missing</div>
          {absent.length > 0 ? (
            <div className="depth-spread-block">
              <strong>Not in ledger (extracted)</strong>
              <ul className="depth-actor-absent-list">
                {absent.map((x) => (
                  <li key={x.name} className="depth-actor-absent-row">
                    <span>{x.name}</span>
                    {x.wikidata_attempted ? (
                      <span className="depth-muted depth-actor-absent-chain" title="No ledger, Wikidata, Wikipedia, or web hit">
                        {" "}
                        (no dynamic match)
                      </span>
                    ) : null}{" "}
                    {onActorDepth ? (
                      entityWorthLookup(x.name) ? (
                        <ActorDepthTrigger
                          entityName={x.name}
                          ledgerHref={null}
                          result={actorDepthByEntity?.[x.name]}
                          loading={actorDepthLoading?.[x.name]}
                          onLookup={onActorDepth}
                        />
                      ) : null
                    ) : (
                      <RabbitNudge href={null} absent={true} />
                    )}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
          {!hasBody ? (
            <p className="depth-muted depth-spread-absent">
              No actor-like spans extracted for ledger lookup.
            </p>
          ) : null}
          <GapChips fields={gaps} showHeader={false} />
        </div>
      ) : null}
    </div>
  );
}

function SpreadResultFields({ spread }) {
  if (!spread || typeof spread !== "object") return null;
  const platforms = spread.platforms_mentioned || [];
  const indicators = spread.spread_indicators || [];
  const absent = spread.absent_fields || [];
  const hasSignals = platforms.length > 0 || indicators.length > 0;
  return (
    <div className="depth-spread-result">
      <div className="depth-spread-head depth-meta-row depth-spread-meta">
        <span className="depth-muted">
          Time compression (heuristic): {spread.time_compression ? "yes" : "no"}
        </span>
        {spread.confidence_tier ? <TierBadge tier={spread.confidence_tier} /> : null}
      </div>
      {hasSignals ? (
        <div className="depth-signals-found">
          <div className="depth-signals-label">Signals found</div>
          {platforms.length > 0 ? (
            <div className="depth-spread-block">
              <strong>Platforms mentioned</strong>
              <ul className="depth-spread-list">
                {platforms.map((p) => (
                  <li key={p}>{p}</li>
                ))}
              </ul>
            </div>
          ) : null}
          {indicators.length > 0 ? (
            <div className="depth-spread-block">
              <strong>Spread indicators</strong>
              <ul className="depth-spread-list">
                {indicators.map((x) => (
                  <li key={x}>{x}</li>
                ))}
              </ul>
            </div>
          ) : null}
        </div>
      ) : null}
      {absent.length > 0 ? (
        <div className="depth-signals-missing">
          <div className="depth-signals-label depth-signals-label--missing">Signals missing</div>
          <GapChips fields={absent} showHeader={false} />
        </div>
      ) : null}
    </div>
  );
}

function MediaClaimsList({
  claims,
  ledgerPresence,
  onActorDepth,
  actorDepthByEntity,
  actorDepthLoading,
}) {
  if (!claims || claims.length === 0) return null;
  return (
    <details className="depth-media-claims">
      <summary className="depth-media-claims-summary">
        Timestamped claims ({claims.length})
      </summary>
      <ul className="depth-media-claim-list">
        {claims.map((c, i) => {
          const sp = (c.speaker || "").trim();
          const skipNudge = !sp || sp.toLowerCase() === "unknown";
          const { checked, resolvedSlug, inLedger } = skipNudge
            ? { checked: true, resolvedSlug: null, inLedger: false }
            : actorLedgerResolved(sp, ledgerPresence);
          return (
            <li key={`${c.timestamp_start ?? i}-${i}`} className="depth-media-claim-item">
              <div className="depth-media-claim-meta">
                <span className="depth-media-ts">{c.timestamp_label || "—"}</span>
                {sp ? (
                  <span className="depth-media-speaker depth-media-speaker-block">
                    <span className="depth-media-speaker-name">{sp}</span>
                    {!skipNudge ? (
                      !checked ? (
                        <span className="depth-muted rabbit-nudge-pending" title="Checking ledger…">
                          {" "}
                          …
                        </span>
                      ) : entityWorthLookup(sp) ? (
                        <ActorDepthTrigger
                          entityName={sp}
                          ledgerHref={
                            inLedger
                              ? `${API}/v1/actor/${encodeURIComponent(resolvedSlug)}`
                              : null
                          }
                          result={actorDepthByEntity[sp]}
                          loading={actorDepthLoading[sp]}
                          onLookup={onActorDepth}
                        />
                      ) : null
                    ) : null}
                  </span>
                ) : null}
                <TierBadge tier={mediaClaimBadgeTier(c)} />
              </div>
              <p className="depth-media-claim-text">{c.text}</p>
            </li>
          );
        })}
      </ul>
    </details>
  );
}

function sourcesCheckedStatusClass(status) {
  const s = String(status || "");
  if (s === "found") return "depth-sc-found";
  if (s === "timeout") return "depth-sc-timeout";
  if (s === "error") return "depth-sc-error";
  if (s === "deferred") return "depth-sc-deferred";
  return "depth-sc-not_found";
}

function SourcesCheckedManifest({ entries }) {
  if (!entries || entries.length === 0) return null;
  const sorted = [...entries].sort((a, b) => String(a.adapter).localeCompare(String(b.adapter)));
  const found = sorted.filter((e) => e.status === "found").length;
  return (
    <details className="depth-sources-checked-wrap">
      <summary className="depth-sources-checked-summary">
        {sorted.length} sources checked — {found} returned results
      </summary>
      <ul className="depth-sources-checked-list">
        {sorted.map((e) => (
          <li key={e.adapter} className="depth-sources-checked-row">
            <code>{e.adapter}</code>
            <span className={`depth-sc-badge ${sourcesCheckedStatusClass(e.status)}`}>{e.status}</span>
          </li>
        ))}
      </ul>
    </details>
  );
}

function FiveRingReportPanel({ report, loading, error }) {
  if (loading) {
    return (
      <section className="depth-five-ring-report">
        <p className="depth-muted">Generating five-ring report…</p>
      </section>
    );
  }
  if (error) {
    return (
      <section className="depth-five-ring-report">
        <p className="depth-banner depth-banner-error">{error}</p>
      </section>
    );
  }
  if (!report) return null;

  if (report.receipt_type === "article_analysis") {
    const claims = report.claims_verified || [];
    const allActorNotFound =
      claims.length > 1 &&
      claims.every((c) => {
        const actorV = (c.verifications || []).filter((v) => v.adapter === "actor_ledger");
        if (actorV.length === 0) return false;
        return actorV.every((v) => v.status === "not_found");
      });
    return (
      <section className="depth-five-ring-report depth-article-analysis-report">
        <h2 className="depth-inline-title depth-five-ring-heading">Article analysis</h2>
        <p className="depth-muted depth-report-meta">
          <code>{report.report_id}</code> · {report.generated_at} ·{" "}
          {report.signed ? "signed" : "unsigned"}
        </p>
        <div className="article-meta">
          <div className="article-pub">{report.article?.publication}</div>
          <div className="article-title">{report.article?.title}</div>
          <div className="article-topic">{report.article_topic}</div>
          <div className="claims-count">
            {report.claims_extracted} claims extracted · {claims.length} routed
          </div>
        </div>
        {report.extraction_error ? (
          <p className="depth-banner-error">Extraction: {report.extraction_error}</p>
        ) : null}
        {allActorNotFound ? (
          <p
            className="depth-muted"
            style={{
              fontSize: "12px",
              marginBottom: "10px",
              padding: "6px 10px",
              background: "rgba(255,255,255,0.03)",
              borderRadius: "6px",
            }}
          >
            Actor ledger: no matches across {claims.length} claims
          </p>
        ) : null}
        {claims.map((c, i) => {
          const hasFound = (c.verifications || []).some((v) => v.status === "found");
          return (
            <AccordionSection
              key={i}
              title={c.claim || "—"}
              statusRight={hasFound ? "found" : "deferred"}
              statusClass={hasFound ? "status-found" : "status-deferred"}
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
                {[...(c.verifications || [])]
                  .filter(
                    (v) =>
                      !(
                        allActorNotFound &&
                        v.adapter === "actor_ledger" &&
                        v.status === "not_found"
                      ),
                  )
                  .sort((a, b) => String(a.adapter).localeCompare(String(b.adapter)))
                  .map((v, j) => (
                    <div key={j} className="verification-row">
                      <span className="adapter-name">{v.adapter}</span>
                      <span className={`status-badge status-${v.status}`}>{v.status}</span>
                      {v.detail ? <span className="status-detail">{v.detail}</span> : null}
                    </div>
                  ))}
              </div>
            </AccordionSection>
          );
        })}
      </section>
    );
  }

  if (!Array.isArray(report.rings)) return null;
  return (
    <section className="depth-five-ring-report">
      <h2 className="depth-inline-title depth-five-ring-heading">Five-ring report</h2>
      <p className="depth-muted depth-report-meta">
        <code>{report.report_id}</code> · {report.generated_at} ·{" "}
        {report.signed ? "signed" : "unsigned"}
      </p>
      <SourcesCheckedManifest entries={report.sources_checked} />
      <div className="depth-ring-list">
        {report.rings.map((r) => (
          <details key={r.ring} className="depth-ring-details">
            <summary className="depth-ring-summary">
              <span className="depth-ring-summary-title">
                Ring {r.ring}: {r.title}
              </span>
              <TierBadge tier={r.confidence_tier} />
            </summary>
            <div className="depth-ring-body">
              {(r.absent_fields || []).length > 0 ? (
                <div className="depth-ring-absent">
                  <GapChips fields={r.absent_fields} />
                </div>
              ) : null}
              {(r.sources || []).length > 0 ? (
                <div className="depth-ring-sources">
                  <strong>Sources</strong>
                  <ul className="depth-spread-list">
                    {(r.sources || []).map((s) => (
                      <li key={s.id}>
                        <span className="depth-muted">{s.adapter}</span> — {s.title}{" "}
                        {s.url ? (
                          <a href={s.url} className="depth-ring-src-link" target="_blank" rel="noreferrer">
                            link
                          </a>
                        ) : null}
                      </li>
                    ))}
                  </ul>
                </div>
              ) : null}
              <pre className="depth-ring-json">{JSON.stringify(r.content, null, 2)}</pre>
            </div>
          </details>
        ))}
      </div>
      {report.unknowns &&
      (report.unknowns.operational?.length > 0 || report.unknowns.epistemic?.length > 0) ? (
        <div className="depth-report-unknowns">
          <strong>Unknowns</strong>
          {report.unknowns.operational?.length > 0 ? (
            <ul className="depth-spread-list">
              {report.unknowns.operational.map((u, i) => (
                <li key={`op-${i}`}>
                  {u.text}{" "}
                  <span className="depth-muted">
                    ({u.resolution_possible ? "operational" : "—"})
                  </span>
                </li>
              ))}
            </ul>
          ) : null}
          {report.unknowns.epistemic?.length > 0 ? (
            <ul className="depth-spread-list">
              {report.unknowns.epistemic.map((u, i) => (
                <li key={`ep-${i}`}>
                  {u.text} <span className="depth-muted">(epistemic)</span>
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}

function LayerCard({ layer, children, isFocused }) {
  const available = layer.depth_available;
  const sealedFloor = layer.layer_number === 6 && !available;

  return (
    <article
      id={`depth-layer-${layer.layer_number}`}
      className={`depth-layer-card ${available ? "depth-layer--available" : "depth-layer--limited"} ${sealedFloor ? "depth-layer--sealed-floor" : ""} ${isFocused ? "depth-layer-card--focused" : ""}`}
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
  const [spreadResult, setSpreadResult] = useState(null);
  const [spreadError, setSpreadError] = useState(null);
  const [originResult, setOriginResult] = useState(null);
  const [originError, setOriginError] = useState(null);
  const [actorLayerResult, setActorLayerResult] = useState(null);
  const [actorLayerError, setActorLayerError] = useState(null);
  const [searchBusy, setSearchBusy] = useState(false);
  const [openDispute, setOpenDispute] = useState(null);
  const [exampleTrace, setExampleTrace] = useState(null);
  const [ledgerPresence, setLedgerPresence] = useState({});
  const [reportPayload, setReportPayload] = useState(null);
  const [reportLoading, setReportLoading] = useState(false);
  const [reportError, setReportError] = useState(null);
  const [reportPulse, setReportPulse] = useState(false);
  const [publicNarrativeResult, setPublicNarrativeResult] = useState(null);
  const [publicNarrativeLoading, setPublicNarrativeLoading] = useState(false);
  const [publicNarrativeError, setPublicNarrativeError] = useState(null);
  const [queryResult, setQueryResult] = useState(null);
  const [queryLoading, setQueryLoading] = useState(false);
  const [queryError, setQueryError] = useState(null);
  const [activeLayer, setActiveLayer] = useState(1);
  const actorDepthInflight = useRef(new Set());
  const [actorDepthByEntity, setActorDepthByEntity] = useState({});
  const [actorDepthLoading, setActorDepthLoading] = useState({});

  const fetchActorDepth = useCallback(async (entityName) => {
    const key = (entityName || "").trim();
    if (!key) return;
    // Block only concurrent in-flight requests for the same key (never skip re-clicks after completion).
    if (actorDepthInflight.current.has(key)) return;
    actorDepthInflight.current.add(key);
    setActorDepthLoading((p) => ({ ...p, [key]: true }));
    try {
      // Name twice: candidateRelevanceScore needs ≥2 (e.g. two mentions); bare name scores 1.
      const narrativeForLayer = `${key} is a named entity referenced in this public record. ${key}.`;
      const res = await fetch(`${API}/v1/actor-layer`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ narrative: narrativeForLayer }),
      });
      let data = {};
      try {
        data = await res.json();
      } catch {
        data = {};
      }
      if (!res.ok) {
        const detail =
          typeof data?.detail === "string"
            ? data.detail
            : data?.detail != null
              ? JSON.stringify(data.detail)
              : `HTTP ${res.status}`;
        setActorDepthByEntity((p) => ({ ...p, [key]: { error: detail } }));
      } else {
        setActorDepthByEntity((p) => ({ ...p, [key]: data }));
      }
    } catch (e) {
      setActorDepthByEntity((p) => ({
        ...p,
        [key]: { error: e.message || "Request failed" },
      }));
    } finally {
      actorDepthInflight.current.delete(key);
      setActorDepthLoading((p) => ({ ...p, [key]: false }));
    }
  }, []);

  const fetchPublicNarrative = useCallback(async (text) => {
    const t = (text || "").trim();
    if (!t) return;
    setPublicNarrativeLoading(true);
    setPublicNarrativeResult(null);
    setPublicNarrativeError(null);
    try {
      const res = await fetch(`${API}/v1/public-narrative`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ narrative: t }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        setPublicNarrativeError(
          typeof data?.detail === "string"
            ? data.detail
            : data?.detail != null
              ? JSON.stringify(data.detail)
              : `HTTP ${res.status}`,
        );
      } else {
        setPublicNarrativeResult(data);
      }
    } catch (e) {
      setPublicNarrativeError(e.message || "Request failed");
    } finally {
      setPublicNarrativeLoading(false);
    }
  }, []);

  const fetchQuery = useCallback(async (text) => {
    const t = (text || "").trim();
    if (!t) return;
    setQueryLoading(true);
    setQueryResult(null);
    setQueryError(null);
    try {
      const res = await fetch(`${API}/v1/query`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          query: t,
          max_sources: 8,
          include_global_perspectives: true,
        }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        setQueryError(
          typeof data?.detail === "string"
            ? data.detail
            : data?.detail != null
              ? JSON.stringify(data.detail)
              : `HTTP ${res.status}`,
        );
      } else {
        setQueryResult(data);
      }
    } catch (e) {
      setQueryError(e.message || "Query failed");
    } finally {
      setQueryLoading(false);
    }
  }, []);

  const traceComplete = useMemo(
    () =>
      !searchBusy &&
      Boolean(narrative.trim()) &&
      (surfaceResult != null ||
        surfaceUnavailable ||
        spreadResult != null ||
        originResult != null ||
        actorLayerResult != null ||
        patternResult != null),
    [
      searchBusy,
      narrative,
      surfaceResult,
      surfaceUnavailable,
      spreadResult,
      originResult,
      actorLayerResult,
      patternResult,
    ],
  );

  const onGenerateReport = useCallback(async () => {
    const text = narrative.trim();
    if (!text) return;
    setReportPulse(true);
    window.setTimeout(() => setReportPulse(false), 1500);
    setQueryResult(null);
    setQueryLoading(false);
    setQueryError(null);
    setActorDepthByEntity({});
    setActorDepthLoading({});
    actorDepthInflight.current.clear();
    setPublicNarrativeResult(null);
    setPublicNarrativeLoading(false);
    setPublicNarrativeError(null);
    setReportLoading(true);
    setReportError(null);
    const isUrl = text.startsWith("http");
    const endpoint = isUrl ? "/v1/analyze-article" : "/v1/report";
    const bodyPayload = isUrl ? { url: text } : { narrative: text };
    try {
      const res = await fetch(`${API}${endpoint}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(bodyPayload),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        setReportError(
          typeof data?.detail === "string"
            ? data.detail
            : data?.detail != null
              ? JSON.stringify(data.detail)
              : `HTTP ${res.status}`,
        );
        setReportPayload(null);
        return;
      }
      setReportPayload(data);
    } catch (e) {
      setReportError(e.message || "Report request failed");
      setReportPayload(null);
    } finally {
      setReportLoading(false);
    }
  }, [narrative]);

  useEffect(() => {
    const slugs = new Set();
    const collect = (t) => {
      if (!t || typeof t !== "object") return;
      for (const w of t.who || []) {
        if (w?.name) {
          for (const s of actorSlugCandidates(w.name)) slugs.add(s);
        }
      }
      for (const c of t.media_claims || []) {
        const sp = (c?.speaker || "").trim();
        if (sp && sp.toLowerCase() !== "unknown") {
          for (const s of actorSlugCandidates(sp)) slugs.add(s);
        }
      }
    };
    collect(surfaceResult);
    collect(exampleTrace);
    if (slugs.size === 0) {
      setLedgerPresence({});
      return;
    }
    let cancelled = false;
    (async () => {
      const next = {};
      await Promise.all(
        [...slugs].map(async (slug) => {
          try {
            const ok = await fetchActorInLedger(slug);
            if (!cancelled) next[slug] = ok;
          } catch {
            if (!cancelled) next[slug] = false;
          }
        }),
      );
      if (!cancelled) setLedgerPresence(next);
    })();
    return () => {
      cancelled = true;
    };
  }, [surfaceResult, exampleTrace]);

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

  const layerStates = useMemo(
    () => ({
      1: searchBusy
        ? "loading"
        : surfaceResult
          ? "found"
          : surfaceError
            ? "error"
            : surfaceUnavailable
              ? "empty"
              : "idle",
      2: searchBusy
        ? "loading"
        : spreadResult
          ? (spreadResult.spread_indicators || []).length > 0 ||
              (spreadResult.platforms_mentioned || []).length > 0
            ? "found"
            : "empty"
          : spreadError
            ? "error"
            : "idle",
      3: searchBusy
        ? "loading"
        : originResult
          ? originResult.anchor_exists
            ? "found"
            : "empty"
          : originError
            ? "error"
            : "idle",
      4: searchBusy
        ? "loading"
        : actorLayerResult
          ? (actorLayerResult.actors_found || []).length > 0
            ? "found"
            : "empty"
          : actorLayerError
            ? "error"
            : "idle",
      5: searchBusy
        ? "loading"
        : patternResult
          ? (patternResult.matches || []).length > 0
            ? "found"
            : "empty"
          : patternError
            ? "error"
            : "idle",
      6: "sealed",
    }),
    [
      searchBusy,
      surfaceResult,
      surfaceError,
      surfaceUnavailable,
      spreadResult,
      spreadError,
      originResult,
      originError,
      actorLayerResult,
      actorLayerError,
      patternResult,
      patternError,
    ],
  );

  const scrollToLayer = useCallback((id) => {
    setActiveLayer(id);
    window.requestAnimationFrame(() => {
      document.getElementById(`depth-layer-${id}`)?.scrollIntoView({
        behavior: "smooth",
        block: "start",
      });
    });
  }, []);

  const onSearch = useCallback(
    async (e) => {
      e.preventDefault();
      const text = narrative.trim();
      if (!text) return;

      if (isNaturalLanguageQuery(text)) {
        setExampleTrace(null);
        setSurfaceResult(null);
        setSurfaceUnavailable(false);
        setSurfaceError(null);
        setPatternResult(null);
        setPatternError(null);
        setSpreadResult(null);
        setSpreadError(null);
        setOriginResult(null);
        setOriginError(null);
        setActorLayerResult(null);
        setActorLayerError(null);
        setOpenDispute(null);
        setReportPayload(null);
        setReportError(null);
        setActorDepthByEntity({});
        setActorDepthLoading({});
        actorDepthInflight.current.clear();
        setPublicNarrativeResult(null);
        setPublicNarrativeLoading(false);
        setPublicNarrativeError(null);
        setQueryResult(null);
        setQueryError(null);
        setQueryLoading(false);
        setSearchBusy(false);
        await fetchQuery(text);
        return;
      }

      setSearchBusy(true);
      setExampleTrace(null);
      setSurfaceResult(null);
      setSurfaceUnavailable(false);
      setSurfaceError(null);
      setPatternResult(null);
      setPatternError(null);
      setSpreadResult(null);
      setSpreadError(null);
      setOriginResult(null);
      setOriginError(null);
      setActorLayerResult(null);
      setActorLayerError(null);
      setOpenDispute(null);
      setReportPayload(null);
      setReportError(null);
      setActorDepthByEntity({});
      setActorDepthLoading({});
      actorDepthInflight.current.clear();
      setPublicNarrativeResult(null);
      setPublicNarrativeLoading(false);
      setPublicNarrativeError(null);
      setQueryResult(null);
      setQueryError(null);
      setQueryLoading(false);

      const narrativeReq = {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ narrative: text }),
      };
      const [sRes, pRes, sprRes, oRes, aRes] = await Promise.all([
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
        fetch(`${API}/v1/spread`, narrativeReq),
        fetch(`${API}/v1/origin`, narrativeReq),
        fetch(`${API}/v1/actor-layer`, narrativeReq),
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

      if (sprRes.ok) {
        setSpreadResult(await sprRes.json());
        setSpreadError(null);
      } else {
        setSpreadResult(null);
        setSpreadError(`Spread analysis failed (${sprRes.status})`);
      }

      if (oRes.ok) {
        setOriginResult(await oRes.json());
        setOriginError(null);
      } else {
        setOriginResult(null);
        setOriginError(`Origin analysis failed (${oRes.status})`);
      }

      if (aRes.ok) {
        setActorLayerResult(await aRes.json());
        setActorLayerError(null);
      } else {
        setActorLayerResult(null);
        setActorLayerError(`Actor layer failed (${aRes.status})`);
      }

      setSearchBusy(false);
    },
    [narrative, fetchQuery],
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
          <button
            type="submit"
            className="depth-btn depth-btn-primary"
            disabled={searchBusy || queryLoading}
          >
            {queryLoading ? "Searching…" : searchBusy ? "Tracing…" : "Trace at depth"}
          </button>
        </div>
        {narrative.trim().startsWith("http") ? (
          <span className="input-mode-hint">URL — will extract and verify claims</span>
        ) : isNaturalLanguageQuery(narrative) ? (
          <span className="input-mode-hint">
            Query detected — will search global sources and synthesize
          </span>
        ) : narrative.trim() ? (
          <span className="input-mode-hint">Narrative — will trace depth layers</span>
        ) : null}
      </form>

      {queryLoading ? (
        <div className="depth-query-loading">
          <p className="depth-muted">Searching curated global RSS feeds…</p>
        </div>
      ) : null}
      {queryError ? <p className="depth-banner-error">{queryError}</p> : null}
      {queryResult ? <QuerySynthesisPanel result={queryResult} /> : null}

      {mapError ? <p className="depth-banner depth-banner-error">{mapError}</p> : null}

      {narrative.trim().startsWith("http") && surfaceResult ? (
        <div className="depth-source-card">
          <div className="depth-source-card-url">{narrative.trim()}</div>
          {surfaceResult.what ? (
            <blockquote className="depth-source-card-quote">{surfaceResult.what}</blockquote>
          ) : null}
          {surfaceResult.what_confidence_tier ? (
            <TierBadge tier={surfaceResult.what_confidence_tier} />
          ) : null}
        </div>
      ) : null}
      {surfaceResult ? (
        <div className="depth-layers-divider">
          <span>Structural layers</span>
        </div>
      ) : null}

      <LayerTabBar activeLayer={activeLayer} onSelect={scrollToLayer} layerStates={layerStates} />

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
          const isL2 = num === 2;
          const isL3 = num === 3;
          const isL4 = num === 4;
          const isL5 = num === 5;

          return (
            <LayerCard key={layer.layer_number} layer={layer} isFocused={activeLayer === num}>
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
                      <div className="depth-surface-result-head">
                        <h3 className="depth-inline-title">Surface trace</h3>
                        {surfaceResult.source_type === "media" ? (
                          <span className="depth-badge-transcribed" title="Transcribed from audio/video">
                            TRANSCRIBED
                          </span>
                        ) : null}
                      </div>
                      <SurfaceTraceFields
                        trace={surfaceResult}
                        ledgerPresence={ledgerPresence}
                        onActorDepth={fetchActorDepth}
                        actorDepthByEntity={actorDepthByEntity}
                        actorDepthLoading={actorDepthLoading}
                        omitWhatForUrl={
                          narrative.trim().startsWith("http") && Boolean(surfaceResult?.what)
                        }
                      />
                      <MediaClaimsList
                        claims={surfaceResult.media_claims}
                        ledgerPresence={ledgerPresence}
                        onActorDepth={fetchActorDepth}
                        actorDepthByEntity={actorDepthByEntity}
                        actorDepthLoading={actorDepthLoading}
                      />
                    </div>
                  ) : null}
                  {exampleTrace && !surfaceResult && !searchBusy ? (
                    <div className="depth-example-trace">
                      <p className="depth-example-label">
                        <em>Example trace — Slenderman (inoculation baseline)</em>
                      </p>
                      <SurfaceTraceFields
                        trace={exampleTrace}
                        ledgerPresence={ledgerPresence}
                        onActorDepth={fetchActorDepth}
                        actorDepthByEntity={actorDepthByEntity}
                        actorDepthLoading={actorDepthLoading}
                        omitWhatForUrl={false}
                      />
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

              {isL2 ? (
                <div className="depth-layer-inline">
                  {searchBusy ? (
                    <p className="depth-muted depth-trace-hint">Tracing spread…</p>
                  ) : null}
                  {!spreadResult && !spreadError && !searchBusy ? (
                    <div className="depth-gp-primary">
                      <p className="depth-muted" style={{ marginBottom: "12px" }}>
                        No platform spread signals detected. The story may be too recent, too
                        regional, or not yet syndicated across tracked channels.
                      </p>
                      {narrative.trim() && !publicNarrativeResult && !publicNarrativeLoading ? (
                        <button
                          type="button"
                          className="depth-btn depth-btn-primary"
                          onClick={() => fetchPublicNarrative(narrative)}
                        >
                          🌍 Show global perspectives
                        </button>
                      ) : null}
                      {publicNarrativeLoading ? (
                        <p className="depth-muted">Pulling global framing analysis…</p>
                      ) : null}
                      {publicNarrativeError ? (
                        <p className="depth-banner-error">{publicNarrativeError}</p>
                      ) : null}
                      {publicNarrativeResult ? (
                        <GlobalPerspectivesPanel result={publicNarrativeResult} />
                      ) : null}
                    </div>
                  ) : null}
                  {spreadError ? <p className="depth-banner-error">{spreadError}</p> : null}
                  {spreadResult ? <SpreadResultFields spread={spreadResult} /> : null}
                  {spreadResult &&
                  !spreadError &&
                  !searchBusy &&
                  ((spreadResult.spread_indicators || []).length > 0 ||
                    (spreadResult.platforms_mentioned || []).length > 0) ? (
                    <div style={{ marginTop: "16px" }}>
                      {narrative.trim() && !publicNarrativeResult && !publicNarrativeLoading ? (
                        <button
                          type="button"
                          className="depth-btn depth-btn-ghost"
                          onClick={() => fetchPublicNarrative(narrative)}
                        >
                          🌍 Show global perspectives
                        </button>
                      ) : null}
                      {publicNarrativeLoading ? (
                        <p className="depth-muted">Pulling global framing analysis…</p>
                      ) : null}
                      {publicNarrativeError ? (
                        <p className="depth-banner-error">{publicNarrativeError}</p>
                      ) : null}
                      {publicNarrativeResult ? (
                        <GlobalPerspectivesPanel result={publicNarrativeResult} />
                      ) : null}
                    </div>
                  ) : null}
                  {spreadResult &&
                  !spreadError &&
                  !searchBusy &&
                  !(spreadResult.spread_indicators || []).length &&
                  !(spreadResult.platforms_mentioned || []).length ? (
                    <div style={{ marginTop: "16px" }}>
                      {narrative.trim() && !publicNarrativeResult && !publicNarrativeLoading ? (
                        <button
                          type="button"
                          className="depth-btn depth-btn-ghost"
                          onClick={() => fetchPublicNarrative(narrative)}
                        >
                          🌍 Show global perspectives
                        </button>
                      ) : null}
                      {publicNarrativeLoading ? (
                        <p className="depth-muted">Pulling global framing analysis…</p>
                      ) : null}
                      {publicNarrativeError ? (
                        <p className="depth-banner-error">{publicNarrativeError}</p>
                      ) : null}
                      {publicNarrativeResult ? (
                        <GlobalPerspectivesPanel result={publicNarrativeResult} />
                      ) : null}
                    </div>
                  ) : null}
                </div>
              ) : null}

              {isL3 ? (
                <div className="depth-layer-inline">
                  {searchBusy ? (
                    <p className="depth-muted depth-trace-hint">Tracing origin…</p>
                  ) : null}
                  {!originResult && !originError && !searchBusy ? (
                    <p className="depth-limited-msg">Limited sourcing available at this depth.</p>
                  ) : null}
                  {originError ? <p className="depth-banner-error">{originError}</p> : null}
                  {originResult ? <OriginResultFields origin={originResult} /> : null}
                </div>
              ) : null}

              {isL4 ? (
                <div className="depth-layer-inline">
                  {searchBusy ? (
                    <p className="depth-muted depth-trace-hint">Resolving actors…</p>
                  ) : null}
                  {!actorLayerResult && !actorLayerError && !searchBusy ? (
                    <p className="depth-limited-msg">Limited sourcing available at this depth.</p>
                  ) : null}
                  {actorLayerError ? <p className="depth-banner-error">{actorLayerError}</p> : null}
                  {actorLayerResult ? (
                    <ActorLayerFields
                      actorLayer={actorLayerResult}
                      onActorDepth={fetchActorDepth}
                      actorDepthByEntity={actorDepthByEntity}
                      actorDepthLoading={actorDepthLoading}
                    />
                  ) : null}
                </div>
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
                                <RabbitNudge
                                  href={`${API}/v1/dispute/${encodeURIComponent(m.pattern_id)}`}
                                  label="disputes"
                                />
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

      {traceComplete || narrative.trim().startsWith("http") ? (
        <div className="depth-report-actions">
          <button
            type="button"
            className={`depth-btn depth-btn-secondary depth-generate-btn ${reportPulse ? "depth-generate-btn--pulse" : ""}`}
            disabled={reportLoading}
            onClick={onGenerateReport}
          >
            {reportLoading ? "Generating…" : "Generate Report"}
          </button>
        </div>
      ) : null}

      <FiveRingReportPanel report={reportPayload} loading={reportLoading} error={reportError} />
    </div>
  );
}
