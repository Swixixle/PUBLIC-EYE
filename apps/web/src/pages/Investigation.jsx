import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import ActionStrip from "../components/ActionStrip.jsx";
import BlindSpots from "../components/BlindSpots.jsx";
import CoalitionMap from "../components/CoalitionMap.jsx";
import CoalitionMapSkeleton from "../components/CoalitionMapSkeleton.jsx";
import Header from "../components/Header.jsx";
import JournalistDossierCard from "../components/JournalistDossierCard.jsx";
import PerspectiveClusters from "../components/PerspectiveClusters.jsx";
import RecordSurface from "../components/RecordSurface.jsx";
import SourcesAndActors from "../components/SourcesAndActors.jsx";
import VerificationSidebar from "../components/VerificationSidebar.jsx";
import { useCoalitionMapPoll } from "../hooks/useCoalitionMapPoll.js";
import { fetchReceipt } from "../lib/api.js";
import { buildInvestigationView } from "../lib/investigationMap.js";

export default function Investigation({ onToast }) {
  const { receipt_id: receiptId } = useParams();
  const [receipt, setReceipt] = useState(null);
  const [notFound, setNotFound] = useState(false);
  const [loadFailed, setLoadFailed] = useState(false);

  useEffect(() => {
    let cancel = false;
    setReceipt(null);
    setNotFound(false);
    setLoadFailed(false);
    (async () => {
      try {
        const r = await fetchReceipt(receiptId);
        if (cancel) return;
        if (!r) setNotFound(true);
        else setReceipt(r);
      } catch (e) {
        if (cancel) return;
        onToast?.(e.message || "Could not load this investigation.");
        setLoadFailed(true);
      }
    })();
    return () => {
      cancel = true;
    };
  }, [receiptId, onToast]);

  if (notFound || loadFailed) {
    return (
      <div className="pe-app">
        <Header />
        <div className="pe-not-found">
          <h1 style={{ fontFamily: "var(--font-display)" }}>PUBLIC EYE</h1>
          <p>
            {loadFailed
              ? "We could not load this investigation. Try again later."
              : "This investigation does not exist or has expired."}
          </p>
          <Link to="/" className="pe-btn pe-btn--primary" style={{ marginTop: 20 }}>
            Back to home
          </Link>
        </div>
      </div>
    );
  }

  if (!receipt) {
    return (
      <div className="pe-app">
        <Header />
        <div className="pe-not-found">
          <p>Loading investigation…</p>
        </div>
      </div>
    );
  }

  const v = buildInvestigationView(receipt);
  const id = v.receiptId;

  const gpRaw = receipt.global_perspectives || receipt.synthesis?.global_perspectives;
  const coalitionEnabled = Boolean(
    gpRaw &&
      (gpRaw.ecosystems?.length ||
        gpRaw.most_divergent_pair ||
        gpRaw.most_irreconcilable),
  );
  const { data: coalitionMap, loading: coalitionLoading } = useCoalitionMapPoll(id, coalitionEnabled);

  const articles = receipt.articles || [];
  const art = receipt.article;

  return (
    <div className="pe-app">
      <Header />
      <article className="pe-inv-page">
        <p className="pe-inv-edu">
          PUBLIC EYE · Evidence-linked analysis of this story, cryptographically signed and verifiable.
        </p>
        <div className="pe-inv-layout">
          <div className="pe-main">
            <header className="pe-beat-1 pe-inv-headline">
              <span className="pe-hook" style={{ margin: 0, flex: 1 }}>
                What is happening?
              </span>
              {v.signed ? <span className="pe-hero-badge" style={{ position: "static" }}>✓ Verified</span> : null}
            </header>
            <p className="pe-beat-1 pe-hook" style={{ marginTop: 4 }}>
              {v.headline}
            </p>

            {coalitionEnabled ? (
              <div className="pe-beat-2" style={{ marginTop: 28 }}>
                {coalitionMap ? (
                  <CoalitionMap data={coalitionMap} />
                ) : coalitionLoading ? (
                  <CoalitionMapSkeleton />
                ) : null}
              </div>
            ) : null}

            <SourcesAndActors receipt={receipt} />

            <h2 className="pe-section-title pe-beat-2">At a glance</h2>
            <ul className="pe-bullets-main pe-beat-2">
              <li>
                <span className="pe-dot pe-dot--cyan" />
                <span>
                  <strong style={{ color: "var(--text-primary)" }}>What we know — </strong>
                  {v.bullets.confirmed.slice(0, 3).join(" ")}
                </span>
              </li>
              <li>
                <span className="pe-dot pe-dot--amber" />
                <span>
                  <strong style={{ color: "var(--text-primary)" }}>What&apos;s disputed — </strong>
                  {v.bullets.disputed.slice(0, 2).join(" ")}
                </span>
              </li>
              <li>
                <span className="pe-dot pe-dot--red" />
                <span>
                  <strong style={{ color: "var(--text-primary)" }}>What&apos;s missing — </strong>
                  {v.bullets.missing.slice(0, 2).join(" ")}
                </span>
              </li>
            </ul>

            <RecordSurface receipt={receipt} />

            <JournalistDossierCard
              journalist={receipt.journalist_receipt}
              layerB={receipt.journalist_receipt?.layer_b}
              layerC={receipt.journalist_receipt?.layer_c}
            />

            {v.globalPerspectives ? (
              <div className="pe-beat-3">
                <PerspectiveClusters globalPerspectives={v.globalPerspectives} />
              </div>
            ) : null}

            {v.blindSpots.length ? (
              <div className="pe-beat-3">
                <BlindSpots items={v.blindSpots} />
              </div>
            ) : null}

            <div id="pe-sources-anchor" className="pe-beat-3" style={{ marginTop: 24 }}>
              <h2 className="pe-section-title">Sources</h2>
              {art?.url ? (
                <div className="pe-sources-mini">
                  Primary article:{" "}
                  <a href={art.url} target="_blank" rel="noopener noreferrer">
                    {art.title || art.url}
                  </a>
                </div>
              ) : null}
              {articles.length > 0 ? (
                <ul style={{ margin: "8px 0 0", paddingLeft: 18, color: "var(--text-secondary)", fontSize: 13 }}>
                  {articles.slice(0, 12).map((a) => (
                    <li key={a.url} style={{ marginBottom: 6 }}>
                      <a href={a.url} target="_blank" rel="noopener noreferrer">
                        {a.title || a.outlet || a.url}
                      </a>
                      {a.outlet ? <span style={{ color: "var(--text-muted)" }}> — {a.outlet}</span> : null}
                    </li>
                  ))}
                </ul>
              ) : null}
              {!art?.url && articles.length === 0 ? (
                <p className="pe-sources-mini">Source links are attached in the verification payload.</p>
              ) : null}
            </div>

            <ActionStrip receiptId={id} />
          </div>

          <VerificationSidebar
            className="pe-sidebar pe-sidebar-desktop"
            receiptId={id}
            receiptType={v.receiptType}
            signed={v.signed}
            generatedAt={v.generatedAt}
          />
        </div>

        <details className="pe-sidebar-mobile">
          <summary>Verification details</summary>
          <VerificationSidebar
            className="pe-sidebar"
            style={{ marginTop: 12, border: "none", padding: 0 }}
            receiptId={id}
            receiptType={v.receiptType}
            signed={v.signed}
            generatedAt={v.generatedAt}
          />
        </details>
      </article>
    </div>
  );
}
