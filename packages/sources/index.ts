import type {
  SourceAdapter,
  SourceAdapterResult,
  SourceQuery,
  SourceRecord,
} from "@frame/types";

function nowIso(): string {
  return new Date().toISOString();
}

/** FEC Open Data API — committee & candidate context (illustrative stub). */
export async function fetchFecContext(
  query: SourceQuery,
): Promise<SourceAdapterResult> {
  const committeeId = String(query.params.committeeId ?? "");
  if (!committeeId) {
    return { sources: [], errors: ["fec: committeeId is required"] };
  }
  const sources: SourceRecord[] = [
    {
      id: `fec-committee-${committeeId}`,
      adapter: "fec",
      url: `https://www.fec.gov/data/committee/${committeeId}/`,
      title: `FEC committee profile ${committeeId}`,
      retrievedAt: nowIso(),
      externalRef: committeeId,
      metadata: { committeeId },
    },
  ];
  return { sources };
}

/** OpenSecrets — money-in-politics summaries (illustrative stub). */
export async function fetchOpenSecretsSummary(
  query: SourceQuery,
): Promise<SourceAdapterResult> {
  const cid = String(query.params.candidateId ?? "");
  if (!cid) {
    return { sources: [], errors: ["opensecrets: candidateId is required"] };
  }
  const sources: SourceRecord[] = [
    {
      id: `os-cand-${cid}`,
      adapter: "opensecrets",
      url: `https://www.opensecrets.org/members-of-congress/summary?cid=${encodeURIComponent(cid)}`,
      title: `OpenSecrets summary ${cid}`,
      retrievedAt: nowIso(),
      externalRef: cid,
      metadata: { candidateId: cid },
    },
  ];
  return { sources };
}

/** ProPublica Congress API — member & votes (illustrative stub). */
export async function fetchProPublicaMember(
  query: SourceQuery,
): Promise<SourceAdapterResult> {
  const bioguide = String(query.params.bioguideId ?? "");
  if (!bioguide) {
    return { sources: [], errors: ["propublica: bioguideId is required"] };
  }
  const sources: SourceRecord[] = [
    {
      id: `pp-member-${bioguide}`,
      adapter: "propublica",
      url: `https://projects.propublica.org/api-docs/congress-api/members`,
      title: `ProPublica Congress API member ${bioguide}`,
      retrievedAt: nowIso(),
      externalRef: bioguide,
      metadata: { bioguideId: bioguide },
    },
  ];
  return { sources };
}

/** Senate LDA / House disclosures — lobbying registrations (illustrative stub). */
export async function fetchLobbyingFiling(
  query: SourceQuery,
): Promise<SourceAdapterResult> {
  const reg = String(query.params.registrationId ?? "");
  if (!reg) {
    return {
      sources: [],
      errors: ["lobbying: registrationId is required"],
    };
  }
  const sources: SourceRecord[] = [
    {
      id: `lda-${reg}`,
      adapter: "lobbying",
      url: `https://lda.senate.gov/filings/public/filing/${encodeURIComponent(reg)}/`,
      title: `Lobbying disclosure ${reg}`,
      retrievedAt: nowIso(),
      externalRef: reg,
      metadata: { registrationId: reg },
    },
  ];
  return { sources };
}

/** SEC EDGAR — issuer filings (illustrative stub). */
export async function fetchEdgarCompany(
  query: SourceQuery,
): Promise<SourceAdapterResult> {
  const cik = String(query.params.cik ?? "");
  if (!cik) {
    return { sources: [], errors: ["edgar: cik is required"] };
  }
  const padded = cik.padStart(10, "0");
  const sources: SourceRecord[] = [
    {
      id: `edgar-${padded}`,
      adapter: "edgar",
      url: `https://www.sec.gov/cgi-bin/browse-edgar?CIK=${padded}&owner=exclude`,
      title: `EDGAR browse CIK ${padded}`,
      retrievedAt: nowIso(),
      externalRef: padded,
      metadata: { cik: padded },
    },
  ];
  return { sources };
}

const registry: Record<string, SourceAdapter> = {
  fec: fetchFecContext,
  opensecrets: fetchOpenSecretsSummary,
  propublica: fetchProPublicaMember,
  lobbying: fetchLobbyingFiling,
  edgar: fetchEdgarCompany,
  manual: async (q) => ({
    sources: (q.params.sources as SourceRecord[] | undefined) ?? [],
  }),
};

/**
 * Dispatches a normalized `SourceQuery` to the matching adapter.
 */
export async function runAdapter(query: SourceQuery): Promise<SourceAdapterResult> {
  const fn = registry[query.kind];
  if (!fn) {
    return { sources: [], errors: [`Unknown adapter: ${query.kind}`] };
  }
  return fn(query);
}

export { registry as sourceAdapterRegistry };
