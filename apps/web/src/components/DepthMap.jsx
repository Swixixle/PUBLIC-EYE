import { useCallback, useEffect, useMemo, useState } from "react";

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

function SurfaceTraceFields({ trace, ledgerPresence }) {
  return (
    <>
      <p className="depth-what">{trace.what}</p>
      {trace.cultural_substrate ? (
        <p className="depth-cultural-substrate">{trace.cultural_substrate}</p>
      ) : null}
      <div className="depth-meta-row">
        <TierBadge tier={trace.what_confidence_tier} />
      </div>
      <div className="depth-who">
        <strong>Who</strong>
        <ul>
          {(trace.who || []).map((w) => {
            const { checked, resolvedSlug, inLedger } = actorLedgerResolved(
              w.name,
              ledgerPresence,
            );
            return (
              <li key={w.name}>
                {w.name} <TierBadge tier={w.confidence_tier} />
                {!checked ? (
                  <span className="depth-muted rabbit-nudge-pending" title="Checking ledger…">
                    …
                  </span>
                ) : (
                  <RabbitNudge
                    href={inLedger ? `${API}/v1/actor/${encodeURIComponent(resolvedSlug)}` : null}
                    absent={!inLedger}
                    label="deeper"
                  />
                )}
              </li>
            );
          })}
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

function OriginResultFields({ origin }) {
  if (!origin || typeof origin !== "object") return null;
  const indicators = origin.first_instance_indicators || [];
  const actors = origin.seeding_actors || [];
  const absent = origin.absent_fields || [];
  return (
    <div className="depth-origin-result">
      <h3 className="depth-inline-title">Origin signals</h3>
      <div className="depth-meta-row depth-spread-meta">
        <TierBadge tier={origin.confidence_tier} />
        <span className="depth-muted">
          Anchor (heuristic): {origin.anchor_exists ? "yes" : "no"}
        </span>
      </div>
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
      ) : (
        <p className="depth-muted depth-spread-absent">
          No first-instance phrases detected. Absent or underspecified:{" "}
          {absent.length > 0 ? absent.join(", ") : "first_instance_indicators"}.
        </p>
      )}
      {actors.length > 0 ? (
        <div className="depth-spread-block">
          <strong>Seeding actors (heuristic)</strong>
          <ul className="depth-spread-list">
            {actors.map((a) => (
              <li key={a}>{a}</li>
            ))}
          </ul>
        </div>
      ) : indicators.length > 0 ? (
        <p className="depth-muted depth-spread-absent">
          No seeding actors or venues extracted.{" "}
          {absent.includes("seeding_actors")
            ? "Absent field: seeding_actors."
            : "Check absent_fields below."}
        </p>
      ) : null}
      {absent.length > 0 ? (
        <p className="depth-muted depth-spread-gaps">Gaps: {absent.join(", ")}.</p>
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

function ActorLayerFields({ actorLayer }) {
  if (!actorLayer || typeof actorLayer !== "object") return null;
  const found = actorLayer.actors_found || [];
  const absent = actorLayer.actors_absent || [];
  const gaps = actorLayer.absent_fields || [];
  const dynamicLookups = actorLayer.dynamic_lookups ?? 0;
  const hasBody = found.length > 0 || absent.length > 0;
  return (
    <div className="depth-actor-layer-result">
      <h3 className="depth-inline-title">Actor ledger</h3>
      <div className="depth-meta-row depth-spread-meta">
        <TierBadge tier={actorLayer.confidence_tier} />
        {dynamicLookups > 0 ? (
          <span className="depth-muted" title="Resolved via Wikidata / Wikipedia / web inference">
            Dynamic: {dynamicLookups}
          </span>
        ) : null}
      </div>
      {found.length > 0 ? (
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
                        {a.surface_who.map((w) => (
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
      ) : null}
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
                <RabbitNudge href={null} absent={true} />
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      {!hasBody ? (
        <p className="depth-muted depth-spread-absent">
          No actor-like spans extracted for ledger lookup.{" "}
          {gaps.length > 0 ? `Gaps: ${gaps.join(", ")}.` : null}
        </p>
      ) : null}
      {hasBody && gaps.length > 0 ? (
        <p className="depth-muted depth-spread-gaps">Gaps: {gaps.join(", ")}.</p>
      ) : null}
    </div>
  );
}

function SpreadResultFields({ spread }) {
  if (!spread || typeof spread !== "object") return null;
  const platforms = spread.platforms_mentioned || [];
  const indicators = spread.spread_indicators || [];
  const absent = spread.absent_fields || [];
  return (
    <div className="depth-spread-result">
      <h3 className="depth-inline-title">Spread signals</h3>
      <div className="depth-meta-row depth-spread-meta">
        <TierBadge tier={spread.confidence_tier} />
        <span className="depth-muted">
          Time compression (heuristic): {spread.time_compression ? "yes" : "no"}
        </span>
      </div>
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
      ) : (
        <p className="depth-muted depth-spread-absent">
          No spread-indicator phrases detected in this narrative. Absent or underspecified:{" "}
          {absent.length > 0 ? absent.join(", ") : "spread_indicators"}.
        </p>
      )}
      {indicators.length > 0 && absent.length > 0 ? (
        <p className="depth-muted depth-spread-gaps">Additional gaps: {absent.join(", ")}.</p>
      ) : null}
    </div>
  );
}

function MediaClaimsList({ claims, ledgerPresence }) {
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
                  <span className="depth-media-speaker">
                    {sp}
                    {!skipNudge ? (
                      !checked ? (
                        <span className="depth-muted rabbit-nudge-pending" title="Checking ledger…">
                          {" "}
                          …
                        </span>
                      ) : (
                        <RabbitNudge
                          href={inLedger ? `${API}/v1/actor/${encodeURIComponent(resolvedSlug)}` : null}
                          absent={!inLedger}
                          label="deeper"
                        />
                      )
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
  const found = entries.filter((e) => e.status === "found").length;
  return (
    <details className="depth-sources-checked-wrap">
      <summary className="depth-sources-checked-summary">
        {entries.length} sources checked — {found} returned results
      </summary>
      <ul className="depth-sources-checked-list">
        {entries.map((e) => (
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
                {(c.verifications || []).map((v, j) => (
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
                  <strong>Absent / gaps</strong>
                  <ul className="depth-spread-list">
                    {(r.absent_fields || []).map((f) => (
                      <li key={f}>{f}</li>
                    ))}
                  </ul>
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
      setSpreadResult(null);
      setSpreadError(null);
      setOriginResult(null);
      setOriginError(null);
      setActorLayerResult(null);
      setActorLayerError(null);
      setOpenDispute(null);
      setReportPayload(null);
      setReportError(null);

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
        {narrative.trim().startsWith("http") ? (
          <span className="input-mode-hint">
            Article URL detected — Generate Report will extract and route claims
          </span>
        ) : (
          <span className="input-mode-hint">Enter a claim, name, or narrative to investigate</span>
        )}
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
          const isL2 = num === 2;
          const isL3 = num === 3;
          const isL4 = num === 4;
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
                      <div className="depth-surface-result-head">
                        <h3 className="depth-inline-title">Surface trace</h3>
                        {surfaceResult.source_type === "media" ? (
                          <span className="depth-badge-transcribed" title="Transcribed from audio/video">
                            TRANSCRIBED
                          </span>
                        ) : null}
                      </div>
                      <SurfaceTraceFields trace={surfaceResult} ledgerPresence={ledgerPresence} />
                      <MediaClaimsList claims={surfaceResult.media_claims} ledgerPresence={ledgerPresence} />
                    </div>
                  ) : null}
                  {exampleTrace && !surfaceResult && !searchBusy ? (
                    <div className="depth-example-trace">
                      <p className="depth-example-label">
                        <em>Example trace — Slenderman (inoculation baseline)</em>
                      </p>
                      <SurfaceTraceFields trace={exampleTrace} ledgerPresence={ledgerPresence} />
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
                    <p className="depth-limited-msg">Limited sourcing available at this depth.</p>
                  ) : null}
                  {spreadError ? <p className="depth-banner-error">{spreadError}</p> : null}
                  {spreadResult ? <SpreadResultFields spread={spreadResult} /> : null}
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
                  {actorLayerResult ? <ActorLayerFields actorLayer={actorLayerResult} /> : null}
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
            className="depth-btn depth-btn-secondary"
            disabled={reportLoading}
            onClick={onGenerateReport}
          >
            {reportLoading ? "Generating report…" : "Generate Report"}
          </button>
        </div>
      ) : null}

      <FiveRingReportPanel report={reportPayload} loading={reportLoading} error={reportError} />
    </div>
  );
}
