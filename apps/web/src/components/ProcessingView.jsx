import { useEffect, useState, useCallback, useRef } from "react";
import Procession from "./Procession.jsx";

const STAGES = [
  "Downloading source...",
  "Transcribing audio...",
  "Extracting claims...",
  "Routing entities...",
  "Assembling dossier...",
  "Signing receipt...",
];

export default function ProcessingView({ jobId, jobError, onComplete, onFailed, onRetry }) {
  const [stageIndex, setStageIndex] = useState(0);
  const [elapsedProgress, setElapsedProgress] = useState(3);
  const [elapsedMs, setElapsedMs] = useState(0);
  const [pollError, setPollError] = useState(null);

  const [liveProgress, setLiveProgress] = useState(null);
  const [liveMessage, setLiveMessage] = useState(null);

  const [transcriptPreview, setTranscriptPreview] = useState("");
  const [wordCount, setWordCount] = useState(0);
  const [claims, setClaims] = useState([]);
  const [entities, setEntities] = useState([]);
  const [layerZero, setLayerZero] = useState(null);
  const layerZeroRef = useRef(null);
  const [lzPulse, setLzPulse] = useState(false);

  const fallbackRef = useRef(null);

  useEffect(() => {
    const t0 = Date.now();
    const iv = setInterval(() => setElapsedMs(Date.now() - t0), 500);
    return () => clearInterval(iv);
  }, []);

  useEffect(() => {
    if (liveProgress != null) return;
    const elapsedSec = elapsedMs / 1000;
    const target = Math.min(94, 4 + (elapsedSec / 180) * 88);
    setElapsedProgress(target);
    const si = Math.min(STAGES.length - 1, Math.floor(elapsedSec / 26));
    setStageIndex(si);
  }, [elapsedMs, liveProgress]);

  const pollOnce = useCallback(async () => {
    if (!jobId) return false;
    try {
      const res = await fetch(`/v1/jobs/${jobId}`);
      if (!res.ok) {
        const t = await res.text();
        throw new Error(t || `HTTP ${res.status}`);
      }
      const job = await res.json();
      if (job.status === "complete" && job.receipt) {
        setLiveProgress(100);
        const lz = layerZeroRef.current;
        const merged = lz?.text
          ? {
              ...job.receipt,
              layer_zero: { text: lz.text, salience_score: lz.salience },
            }
          : job.receipt;
        onComplete(merged);
        return true;
      }
      if (job.status === "failed") {
        onFailed(job.error || "Job failed");
        return true;
      }
    } catch (e) {
      setPollError(e.message || "Poll failed");
    }
    return false;
  }, [jobId, onComplete, onFailed]);

  const startFallbackPoll = useCallback(() => {
    if (fallbackRef.current != null) return;
    fallbackRef.current = window.setInterval(async () => {
      const done = await pollOnce();
      if (done && fallbackRef.current != null) {
        window.clearInterval(fallbackRef.current);
        fallbackRef.current = null;
      }
    }, 3000);
  }, [pollOnce]);

  useEffect(() => {
    if (!jobId) return undefined;

    let es;
    try {
      es = new EventSource(`/v1/jobs/${jobId}/stream`);
    } catch {
      startFallbackPoll();
      pollOnce();
      return () => {
        if (fallbackRef.current != null) {
          window.clearInterval(fallbackRef.current);
          fallbackRef.current = null;
        }
      };
    }

    es.onmessage = (e) => {
      try {
        const data = JSON.parse(e.data);

        if (data.event === "stage_update") {
          setLiveMessage(data.message || "");
          if (typeof data.progress === "number") setLiveProgress(data.progress);
        }

        if (data.event === "transcript_ready") {
          setTranscriptPreview(data.transcript_preview || "");
          setWordCount(Number(data.word_count) || 0);
        }

        if (data.event === "claim_found" && data.claim) {
          const c = data.claim;
          setClaims((prev) => {
            const id = c.id || c.statement;
            if (prev.some((x) => (x.id || x.statement) === id)) return prev;
            return [...prev, c];
          });
        }

        if (data.event === "entity_detected" && data.entity_name) {
          setEntities((prev) => {
            if (prev.includes(data.entity_name)) return prev;
            return [...prev, data.entity_name];
          });
        }

        if (data.event === "layer_zero_draft") {
          const lz = {
            text: data.text || "",
            salience: data.salience,
            isDraft: true,
          };
          setLayerZero(lz);
          layerZeroRef.current = lz;
        }

        if (data.event === "layer_zero_final") {
          const lz = {
            text: data.text || "",
            salience: data.salience,
            isDraft: false,
          };
          setLayerZero(lz);
          layerZeroRef.current = lz;
          setLzPulse(true);
          window.setTimeout(() => setLzPulse(false), 900);
        }

        if (data.event === "receipt_sealed") {
          es.close();
          fetch(`/v1/jobs/${jobId}`)
            .then((r) => r.json())
            .then((job) => {
              if (job.receipt) {
                setLiveProgress(100);
                const lz = layerZeroRef.current;
                const merged = lz?.text
                  ? {
                      ...job.receipt,
                      layer_zero: {
                        text: lz.text,
                        salience_score: lz.salience,
                      },
                    }
                  : job.receipt;
                onComplete(merged);
              }
            })
            .catch(() => {});
        }

        if (data.event === "error") {
          es.close();
          onFailed(data.message || "Pipeline error");
        }
      } catch (err) {
        console.error("SSE parse error", err);
      }
    };

    es.onerror = () => {
      try {
        es.close();
      } catch {
        /* ignore */
      }
      startFallbackPoll();
      pollOnce();
    };

    return () => {
      try {
        es.close();
      } catch {
        /* ignore */
      }
      if (fallbackRef.current != null) {
        window.clearInterval(fallbackRef.current);
        fallbackRef.current = null;
      }
    };
  }, [jobId, onComplete, onFailed, pollOnce, startFallbackPoll]);

  const displayProgress = liveProgress != null ? liveProgress : elapsedProgress;
  const displayStage = liveMessage || STAGES[stageIndex];

  const transcriptWords =
    wordCount > 0 ? wordCount : elapsedMs > 8000 ? Math.max(120, Math.floor(elapsedMs / 40)) : 0;

  const shownClaims = claims.slice(0, 5);
  const moreClaims = Math.max(0, claims.length - 5);

  if (jobError) {
    return (
      <div className="processing-view view-enter">
        <p className="processing-title">Blowing the whistle...</p>
        <div className="processing-error">
          The wind found nothing. Check your URL and try again.
          <br />
          <span style={{ fontSize: "0.8rem", opacity: 0.9 }}>{jobError}</span>
          <button type="button" className="processing-retry" onClick={onRetry}>
            Try again
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="processing-view view-enter">
      <div className="processing-top">
        <span className="processing-mark">WHISTLE</span>
      </div>
      <p className="processing-title">Blowing the whistle...</p>

      <Procession stage={displayStage} progress={displayProgress} />

      <div className="processing-status-row">
        <span className="processing-dot" />
        <span className="processing-stage">{displayStage}</span>
      </div>

      {transcriptPreview || transcriptWords > 0 ? (
        <p className="processing-sub processing-transcript-line">
          {wordCount > 0 ? (
            <>
              Transcript: {wordCount} words — {(transcriptPreview || "").slice(0, 100)}
              {(transcriptPreview || "").length > 100 ? "…" : ""}
            </>
          ) : (
            <>Transcript in progress — about {transcriptWords} words so far (estimate)</>
          )}
        </p>
      ) : null}

      <div className={`processing-live-shell ${lzPulse ? "processing-lz-pulse" : ""}`}>
        <div className="processing-live-label">LAYER ZERO</div>
        <div className={`processing-live-lz ${layerZero?.text ? "has-text" : ""}`}>
          {!layerZero?.text ? (
            <div className="skeleton processing-live-lz-skel" />
          ) : (
            <>
              {layerZero.isDraft ? (
                <span className="processing-draft-badge">DRAFT</span>
              ) : null}
              <p className="processing-live-lz-text">{layerZero.text}</p>
              {layerZero.salience != null && layerZero.salience !== "" ? (
                <p className="processing-live-lz-meta">salience: {Number(layerZero.salience).toFixed(2)}</p>
              ) : null}
            </>
          )}
        </div>

        <div className="processing-live-label processing-live-entities-label">ENTITIES DETECTED</div>
        <div className="processing-live-pills">
          {entities.length === 0
            ? [0, 1, 2].map((i) => <span key={i} className="skeleton processing-live-pill-skel" />)
            : entities.map((name) => (
                <span key={name} className="processing-live-pill processing-live-pill-in">
                  {name}
                </span>
              ))}
        </div>

        <div className="processing-live-label">CLAIMS</div>
        <div className="processing-live-claims">
          {claims.length === 0
            ? [0, 1, 2].map((i) => <div key={i} className="skeleton processing-live-claim-skel" />)
            : shownClaims.map((c) => (
                <div key={c.id || c.statement} className="processing-live-claim processing-live-claim-in">
                  <span className="processing-live-claim-dot" />
                  <span className="processing-live-claim-txt">&ldquo;{(c.statement || "").slice(0, 160)}&rdquo;</span>
                </div>
              ))}
          {moreClaims > 0 ? (
            <p className="processing-live-more">{moreClaims} more extracting…</p>
          ) : null}
        </div>
      </div>

      <div className="progress-wrap">
        <div className="progress-bar" style={{ width: `${Math.min(displayProgress, 100)}%` }} />
      </div>

      {pollError ? (
        <div className="processing-error">
          {pollError}
          <button type="button" className="processing-retry" onClick={onRetry}>
            Try again
          </button>
        </div>
      ) : null}
    </div>
  );
}
