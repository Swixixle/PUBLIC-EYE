/**
 * First-class journalist investigation receipt (from article_analysis.journalist_receipt)
 * plus optional Layer B / C web-research blocks.
 */

const MUTED = { color: "var(--text-muted)", fontSize: 13 };
const BODY = { color: "var(--text-secondary)", fontSize: 14, lineHeight: 1.55 };

function CitationList({ urls }) {
  if (!Array.isArray(urls) || !urls.length) return null;
  return (
    <ul style={{ margin: "8px 0 0", paddingLeft: 18, fontSize: 12 }}>
      {urls.slice(0, 12).map((u) => (
        <li key={u} style={{ marginBottom: 4 }}>
          <a href={u} target="_blank" rel="noopener noreferrer">
            {u}
          </a>
        </li>
      ))}
    </ul>
  );
}

function SonarSection({ title, record }) {
  if (!record || typeof record !== "object") return null;
  const { ok, text, detail, citations } = record;
  const cite = Array.isArray(citations) ? citations : [];
  if (!text && !detail && !cite.length) return null;
  return (
    <div style={{ marginTop: 16 }}>
      <h4
        style={{
          fontFamily: "var(--font-body)",
          fontSize: "0.8125rem",
          fontWeight: 600,
          color: "var(--text-primary)",
          margin: "0 0 6px",
        }}
      >
        {title}
      </h4>
      {ok === false && detail ? (
        <p style={{ ...MUTED, margin: "0 0 6px" }}>{detail}</p>
      ) : null}
      {text ? (
        <p style={{ ...BODY, margin: 0, whiteSpace: "pre-wrap" }}>{text}</p>
      ) : null}
      <CitationList urls={cite} />
    </div>
  );
}

function formatMoney(n) {
  if (n == null || n === "") return null;
  const x = typeof n === "number" ? n : parseFloat(n);
  if (Number.isNaN(x)) return String(n);
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 }).format(x);
}

function PublicRecordsSummary({ journalist }) {
  const fec = journalist.fec_donations;
  const cl = journalist.courtlistener_opinions;
  const member = journalist.congress_member;
  const votes = journalist.congress_votes;
  const bills = journalist.congress_bills;
  const sec = journalist.sec_edgar;
  const lda = journalist.lda_filings;
  const quoted = journalist.quoted_sources;

  const hasFec = Array.isArray(fec) && fec.length > 0;
  const hasCl = Array.isArray(cl) && cl.length > 0;
  const hasMember = member && typeof member === "object" && (member.full_name || member.member_id);
  const hasVotes = Array.isArray(votes) && votes.length > 0;
  const hasBills = bills && typeof bills === "object" && Array.isArray(bills.bills) && bills.bills.length > 0;
  const hasSec = sec && typeof sec === "object" && Array.isArray(sec.entities) && sec.entities.length > 0;
  const hasLda = lda && typeof lda === "object" && (lda.filingCount > 0 || (Array.isArray(lda.filings) && lda.filings.length > 0));
  const hasQuoted = Array.isArray(quoted) && quoted.length > 0;

  if (!hasFec && !hasCl && !hasMember && !hasVotes && !hasBills && !hasSec && !hasLda && !hasQuoted) return null;

  return (
    <div style={{ marginTop: 18 }}>
      <h3 className="pe-record-sub" style={{ marginBottom: 8 }}>
        Public records (signed adapters)
      </h3>
      {hasFec ? (
        <ul style={{ ...BODY, margin: "8px 0 0", paddingLeft: 18 }}>
          {fec.slice(0, 8).map((row, i) => (
            <li key={i} style={{ marginBottom: 6 }}>
              {row.contributor_name || row.committee_name || "Contribution"}
              {row.contribution_receipt_amount != null ? (
                <span style={MUTED}> — {formatMoney(row.contribution_receipt_amount)}</span>
              ) : null}
            </li>
          ))}
        </ul>
      ) : null}
      {hasCl ? (
        <ul style={{ ...BODY, margin: "12px 0 0", paddingLeft: 18 }}>
          {cl.slice(0, 5).map((row, i) => (
            <li key={i} style={{ marginBottom: 6 }}>
              {row.url ? (
                <a href={row.url} target="_blank" rel="noopener noreferrer">
                  {row.case_name || "Court opinion"}
                </a>
              ) : (
                row.case_name || "Court opinion"
              )}
              {row.court ? <span style={MUTED}> — {row.court}</span> : null}
            </li>
          ))}
        </ul>
      ) : null}
      {hasMember ? (
        <p style={{ ...BODY, margin: "12px 0 0" }}>
          Congress (ProPublica):{" "}
          <strong style={{ color: "var(--text-primary)" }}>{member.full_name || member.member_id}</strong>
          {member.party || member.state ? (
            <span style={MUTED}>
              {" "}
              ({[member.party, member.state].filter(Boolean).join(", ")})
            </span>
          ) : null}
        </p>
      ) : null}
      {hasVotes ? (
        <ul style={{ ...BODY, margin: "8px 0 0", paddingLeft: 18 }}>
          {votes.slice(0, 5).map((v, i) => (
            <li key={i} style={{ marginBottom: 4 }}>
              {v.bill || v.nomination || "Vote"}
              {v.vote_position ? <span style={MUTED}> — {v.vote_position}</span> : null}
            </li>
          ))}
        </ul>
      ) : null}
      {hasBills ? (
        <ul style={{ ...BODY, margin: "8px 0 0", paddingLeft: 18 }}>
          {bills.bills.slice(0, 5).map((b, i) => (
            <li key={b.bill_id || i} style={{ marginBottom: 4 }}>
              {b.title || b.bill_id || "Bill"}
            </li>
          ))}
        </ul>
      ) : null}
      {hasSec ? (
        <ul style={{ ...BODY, margin: "8px 0 0", paddingLeft: 18 }}>
          {sec.entities.slice(0, 4).map((e, i) => (
            <li key={e.cik || i} style={{ marginBottom: 4 }}>
              {e.name || "SEC entity"}
              {e.cik ? <span style={MUTED}> — CIK {e.cik}</span> : null}
            </li>
          ))}
        </ul>
      ) : null}
      {hasLda ? (
        <p style={{ ...BODY, margin: "12px 0 0" }}>
          LDA filings indexed:{" "}
          <strong style={{ color: "var(--text-primary)" }}>{lda.filingCount ?? lda.filings?.length ?? "—"}</strong>
        </p>
      ) : null}
      {hasQuoted ? (
        <div style={{ marginTop: 12 }}>
          <span style={{ ...BODY, fontWeight: 600, color: "var(--text-primary)" }}>Quoted sources in article</span>
          <ul style={{ ...BODY, margin: "6px 0 0", paddingLeft: 18 }}>
            {quoted.slice(0, 8).map((q, i) => (
              <li key={q.name || i} style={{ marginBottom: 4 }}>
                {q.name || JSON.stringify(q)}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}

function AdapterMeta({ meta }) {
  if (!meta || typeof meta !== "object") return null;
  const adapters = meta.adapters;
  if (!adapters || typeof adapters !== "object") return null;
  const entries = Object.entries(adapters);
  if (!entries.length) return null;
  return (
    <div style={{ marginTop: 14, ...MUTED }}>
      Adapter status ({meta.wall_time_ms != null ? `${meta.wall_time_ms} ms` : "timing n/a"})
      <ul style={{ margin: "6px 0 0", paddingLeft: 18, fontSize: 12 }}>
        {entries.slice(0, 14).map(([name, row]) => (
          <li key={name} style={{ marginBottom: 3 }}>
            {name}: {row?.status ?? "—"}
            {row?.latency_ms != null ? <span> ({row.latency_ms} ms)</span> : null}
          </li>
        ))}
      </ul>
    </div>
  );
}

function LayerCEntity({ layerC }) {
  if (!layerC || typeof layerC !== "object") return null;
  const keys = Object.keys(layerC).filter((k) => k !== "wall_time_ms");
  if (!keys.length) return null;
  const primitive = keys.every((k) => {
    const v = layerC[k];
    return v == null || typeof v === "string" || typeof v === "number" || typeof v === "boolean";
  });
  if (primitive) {
    return (
      <div style={{ marginTop: 18 }}>
        <h3 className="pe-record-sub" style={{ marginBottom: 8 }}>
          Layer C
        </h3>
        <dl style={{ ...BODY, margin: 0 }}>
          {keys.map((k) => (
            <div key={k} style={{ marginBottom: 6 }}>
              <dt style={{ display: "inline", fontWeight: 600, color: "var(--text-primary)" }}>{k}</dt>
              <dd style={{ display: "inline", margin: 0 }}>: {String(layerC[k])}</dd>
            </div>
          ))}
        </dl>
      </div>
    );
  }
  return (
    <div style={{ marginTop: 18 }}>
      <h3 className="pe-record-sub" style={{ marginBottom: 8 }}>
        Layer C
      </h3>
      {keys.map((k) => {
        const v = layerC[k];
        if (v && typeof v === "object" && ("text" in v || "citations" in v || "ok" in v)) {
          return <SonarSection key={k} title={k.replace(/_/g, " ")} record={v} />;
        }
        return (
          <pre
            key={k}
            style={{
              ...MUTED,
              fontSize: 11,
              overflow: "auto",
              maxHeight: 200,
              padding: 10,
              background: "var(--bg-card)",
              border: "1px solid var(--border)",
              borderRadius: 4,
              marginTop: 8,
            }}
          >
            {k}: {JSON.stringify(v, null, 2)}
          </pre>
        );
      })}
    </div>
  );
}

export default function JournalistDossierCard({ journalist, layerB, layerC }) {
  if (!journalist || typeof journalist !== "object") return null;

  const subject = journalist.subject && typeof journalist.subject === "object" ? journalist.subject : {};
  const name = subject.display_name;
  const publication = subject.publication;
  const b = layerB !== undefined ? layerB : journalist.layer_b;
  const c = layerC !== undefined ? layerC : journalist.layer_c;

  const meta = journalist.investigation_meta;
  const signed = journalist.signed === true;
  const rid = journalist.report_id;

  return (
    <section className="pe-record-section pe-beat-2 pe-journalist-dossier-card" style={{ marginTop: 28 }}>
      <h2 className="pe-record-title">Journalist investigation</h2>
      <p style={{ ...MUTED, margin: "6px 0 0" }}>
        First-class receipt{signed ? " · signed" : ""}
        {rid ? ` · ${rid}` : ""}
      </p>
      {name || publication ? (
        <div className="pe-record-row" style={{ marginTop: 12 }}>
          {name ? <strong style={{ color: "var(--text-primary)" }}>{name}</strong> : null}
          {publication ? <span style={MUTED}>{name ? " · " : ""}{publication}</span> : null}
        </div>
      ) : null}
      {journalist.linked_article_url ? (
        <div className="pe-record-row" style={{ marginTop: 8 }}>
          <span style={BODY}>Linked article: </span>
          <a href={journalist.linked_article_url} target="_blank" rel="noopener noreferrer">
            {journalist.linked_article_url}
          </a>
        </div>
      ) : null}

      <PublicRecordsSummary journalist={journalist} />
      <AdapterMeta meta={meta} />

      {b && typeof b === "object" ? (
        <div style={{ marginTop: 20 }}>
          <h3 className="pe-record-sub" style={{ marginBottom: 4 }}>
            Layer B (web research, cited, not signed)
          </h3>
          <p style={{ ...MUTED, margin: "0 0 8px", fontSize: 12 }}>
            Sonar-sourced context. Verify citations independently.
          </p>
          <SonarSection title="Prior coverage" record={b.prior_coverage} />
          <SonarSection title="Prior positions & beats" record={b.prior_positions} />
          <SonarSection title="Affiliations" record={b.affiliations} />
          <SonarSection title="Corrections & retractions (candidates)" record={b.recant_candidates} />
          {Array.isArray(b.source_audits) && b.source_audits.length > 0 ? (
            <div style={{ marginTop: 16 }}>
              <h4
                style={{
                  fontFamily: "var(--font-body)",
                  fontSize: "0.8125rem",
                  fontWeight: 600,
                  color: "var(--text-primary)",
                  margin: "0 0 8px",
                }}
              >
                Source audits
              </h4>
              {b.source_audits.map((row, idx) => {
                if (!row || typeof row !== "object") return null;
                const label = row.source_name || "Source";
                const { source_name: _sn, ...rest } = row;
                return <SonarSection key={`${label}-${idx}`} title={label} record={rest} />;
              })}
            </div>
          ) : null}
          {b.wall_time_ms != null ? (
            <p style={{ ...MUTED, margin: "14px 0 0", fontSize: 12 }}>Layer B wall time: {b.wall_time_ms} ms</p>
          ) : null}
        </div>
      ) : null}

      <LayerCEntity layerC={c} />
    </section>
  );
}
