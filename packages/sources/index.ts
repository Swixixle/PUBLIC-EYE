import type {
  FrameReceiptPayload,
  SourceAdapter,
  SourceAdapterResult,
  SourceQuery,
  SourceRecord,
} from "@frame/types";

function nowIso(): string {
  return new Date().toISOString();
}

export async function fetchFecContext(
  query: SourceQuery,
): Promise<SourceAdapterResult> {
  const candidateId = String(query.params.candidateId ?? "");
  if (!candidateId) {
    return { sources: [], errors: ["fec: candidateId is required"] };
  }

  const apiKey = (query.params.apiKey as string | undefined) ?? "DEMO_KEY";
  const baseUrl = "https://api.open.fec.gov/v1";
  const sources: SourceRecord[] = [];
  const errors: string[] = [];
  let candidateName = candidateId;
  let allCycleTotals: Array<{
    cycle: number;
    receipts: number;
    pacContributions: number;
    individualContributions: number;
    electionYear: number;
  }> = [];

  try {
    const searchUrl = `${baseUrl}/candidates/?candidate_id=${candidateId}&api_key=${apiKey}`;
    const searchRes = await fetch(searchUrl);
    const searchData = await searchRes.json() as {
      results?: Array<{
        name?: string;
        office_full?: string;
        state?: string;
        party_full?: string;
        election_years?: number[];
      }>;
    };
    if (searchData.results?.[0]) {
      const c = searchData.results[0];
      candidateName = c.name ?? candidateId;
      sources.push({
        id: `fec-candidate-${candidateId}`,
        adapter: "fec",
        url: searchUrl,
        title: `FEC candidate profile: ${candidateName}`,
        retrievedAt: nowIso(),
        externalRef: candidateId,
        metadata: {
          candidateId,
          candidateName,
          office: c.office_full ?? null,
          state: c.state ?? null,
          party: c.party_full ?? null,
          electionYears:
            c.election_years != null ? JSON.stringify(c.election_years) : null,
        },
      });
    }
  } catch (e) {
    errors.push(`fec candidate search failed: ${String(e)}`);
  }

  try {
    const totalsUrl = `${baseUrl}/candidates/totals/?candidate_id=${candidateId}&api_key=${apiKey}&per_page=20&sort=-election_year`;
    const totalsRes = await fetch(totalsUrl);
    const totalsData = await totalsRes.json() as {
      results?: Array<{
        cycle?: number;
        receipts?: number;
        other_political_committee_contributions?: number;
        individual_itemized_contributions?: number;
        election_year?: number;
      }>;
    };
    allCycleTotals = (totalsData.results ?? [])
      .map((r) => ({
        cycle: r.cycle ?? 0,
        receipts: r.receipts ?? 0,
        pacContributions: r.other_political_committee_contributions ?? 0,
        individualContributions: r.individual_itemized_contributions ?? 0,
        electionYear: r.election_year ?? r.cycle ?? 0,
      }))
      .filter((r) => r.receipts > 0);

    sources.push({
      id: `fec-totals-${candidateId}`,
      adapter: "fec",
      url: totalsUrl,
      title: `FEC fundraising totals by cycle: ${candidateName}`,
      retrievedAt: nowIso(),
      externalRef: candidateId,
      metadata: {
        candidateId,
        allCycleTotalsJson: JSON.stringify(allCycleTotals),
      },
    });
  } catch (e) {
    errors.push(`fec totals lookup failed: ${String(e)}`);
  }

  return {
    sources,
    errors: errors.length ? errors : undefined,
    metadata: { candidateName, allCycleTotals },
  };
}

export async function buildLiveFecReceipt(
  candidateId: string,
  apiKey: string = "DEMO_KEY",
): Promise<FrameReceiptPayload> {
  const result = await fetchFecContext({
    kind: "fec",
    params: { candidateId, apiKey },
  });

  const { candidateName = candidateId, allCycleTotals = [] } = (result.metadata ?? {}) as {
    candidateName?: string;
    allCycleTotals?: Array<{
      cycle: number;
      receipts: number;
      pacContributions: number;
      individualContributions: number;
      electionYear: number;
    }>;
  };

  const sources = result.sources;
  const narrative: Array<{ text: string; sourceId: string }> = [];
  const totalsSourceId = `fec-totals-${candidateId}`;

  if (!sources.find((s) => s.id === totalsSourceId)) {
    sources.push({
      id: totalsSourceId,
      adapter: "fec",
      url: `https://api.open.fec.gov/v1/candidates/totals/?candidate_id=${candidateId}`,
      title: `FEC fundraising totals: ${candidateName}`,
      retrievedAt: nowIso(),
      externalRef: candidateId,
      metadata: { note: "API unavailable at signing time" },
    });
  }

  if (allCycleTotals.length === 0) {
    narrative.push({
      text: `FEC records were queried for candidate ${candidateName} (ID: ${candidateId}) at signing time. No fundraising totals were returned.`,
      sourceId: totalsSourceId,
    });
  } else {
    const careerTotal = allCycleTotals.reduce((sum, c) => sum + c.receipts, 0);
    const careerPac = allCycleTotals.reduce((sum, c) => sum + c.pacContributions, 0);
    const pacPct = careerTotal > 0 ? ((careerPac / careerTotal) * 100).toFixed(1) : "0";

    narrative.push({
      text: `According to FEC records, ${candidateName} (ID: ${candidateId}) raised a total of $${careerTotal.toLocaleString()} across ${allCycleTotals.length} election cycle(s) on record.`,
      sourceId: totalsSourceId,
    });

    narrative.push({
      text: `Of that total, $${careerPac.toLocaleString()} (${pacPct}%) came from PACs and other political committees, with $${(careerTotal - careerPac).toLocaleString()} from individual contributors.`,
      sourceId: totalsSourceId,
    });

    const electionCycles = allCycleTotals.filter((c) => c.electionYear === c.cycle);
    for (const c of electionCycles.slice(0, 3)) {
      narrative.push({
        text: `In the ${c.cycle} election cycle, ${candidateName} raised $${c.receipts.toLocaleString()} total, including $${c.pacContributions.toLocaleString()} from PACs.`,
        sourceId: totalsSourceId,
      });
    }
  }

  return {
    schemaVersion: "1.0.0",
    receiptId: crypto.randomUUID(),
    createdAt: new Date().toISOString(),
    claims: [
      {
        id: "claim-1",
        statement: `Live FEC fundraising record for ${candidateName} (${candidateId})`,
        assertedAt: new Date().toISOString(),
      },
    ],
    sources,
    narrative,
    contentHash: "",
  };
}

/** Senate LDA — live lobbying filings + lobbyist directory (no API key). */
export async function buildLiveLobbyingReceipt(
  senatorName: string,
  fecCandidateId?: string,
): Promise<FrameReceiptPayload> {
  const name = senatorName.trim();
  if (!name) {
    throw new Error("buildLiveLobbyingReceipt: senatorName is required");
  }

  const base = "https://lda.senate.gov/api/v1";
  const filingsUrl = `${base}/filings/?filing_year=2024&filing_type=RR&registrant_name=${encodeURIComponent(name)}&limit=5&offset=0`;
  const lobbyistsUrl = `${base}/lobbyists/?name=${encodeURIComponent(name)}&limit=10`;

  type LdaLobbyingActivity = {
    general_issue_code?: string;
    general_issue_code_display?: string;
  };
  type LdaFiling = {
    filing_year?: number;
    income?: number | null;
    registrant?: { name?: string };
    client?: { name?: string };
    lobbying_activities?: LdaLobbyingActivity[];
    url?: string;
  };
  type LdaLobbyistRow = {
    first_name?: string;
    last_name?: string;
    registrant?: { name?: string };
  };

  let filings: LdaFiling[] = [];
  let lobbyistRows: LdaLobbyistRow[] = [];
  let filingsOk = false;
  let lobbyistsOk = false;

  try {
    const res = await fetch(filingsUrl);
    if (res.ok) {
      const data = (await res.json()) as { results?: LdaFiling[] };
      filings = data.results ?? [];
      filingsOk = true;
    }
  } catch {
    /* leave filings empty */
  }

  try {
    const res = await fetch(lobbyistsUrl);
    if (res.ok) {
      const data = (await res.json()) as { results?: LdaLobbyistRow[] };
      lobbyistRows = data.results ?? [];
      lobbyistsOk = true;
    }
  } catch {
    /* leave lobbyists empty */
  }

  const sources: SourceRecord[] = [
    {
      id: "lda-filings-rr-2024",
      adapter: "lobbying",
      url: filingsUrl,
      title: `Senate LDA: registrations (RR, 2024) — registrant name search: ${name}`,
      retrievedAt: nowIso(),
      externalRef: fecCandidateId ?? name,
      metadata: {
        query: name,
        filingCount: filingsOk ? filings.length : 0,
        fecCandidateId: fecCandidateId ?? null,
      },
    },
    {
      id: "lda-lobbyists-name",
      adapter: "lobbying",
      url: lobbyistsUrl,
      title: `Senate LDA: lobbyist directory — name search: ${name}`,
      retrievedAt: nowIso(),
      externalRef: fecCandidateId ?? name,
      metadata: {
        query: name,
        matchCount: lobbyistsOk ? lobbyistRows.length : 0,
        fecCandidateId: fecCandidateId ?? null,
      },
    },
  ];

  const narrative: Array<{ text: string; sourceId: string }> = [];
  const claimSuffix = fecCandidateId ? ` (${fecCandidateId})` : "";

  if (!filingsOk) {
    narrative.push({
      text: `Senate LDA filings search could not be completed for “${name}” at signing time.`,
      sourceId: "lda-filings-rr-2024",
    });
  } else if (filings.length === 0) {
    narrative.push({
      text: `According to Senate LDA disclosures, no 2024 registration filings (type RR) matched registrant name “${name}” in the queried result set.`,
      sourceId: "lda-filings-rr-2024",
    });
  } else {
    for (const f of filings) {
      const registrant = f.registrant?.name ?? "Unknown registrant";
      const client = f.client?.name ?? "Unknown client";
      const year = f.filing_year ?? 2024;
      const income = f.income;
      const codes = [...new Set(
        (f.lobbying_activities ?? [])
          .map((a) => a.general_issue_code_display ?? a.general_issue_code ?? "")
          .filter(Boolean),
      )].slice(0, 12);
      const codesText = codes.length ? codes.join(", ") : "no issue codes listed";

      if (income != null && typeof income === "number") {
        narrative.push({
          text: `According to Senate LDA disclosures, ${registrant} reported $${income.toLocaleString()} in lobbying income from ${client} in ${year}. Issue areas on file include: ${codesText}.`,
          sourceId: "lda-filings-rr-2024",
        });
      } else {
        narrative.push({
          text: `According to Senate LDA disclosures, ${registrant} filed a registration involving ${client} in ${year}, with no income figure in this filing record. Issue areas on file include: ${codesText}.`,
          sourceId: "lda-filings-rr-2024",
        });
      }
    }
  }

  if (!lobbyistsOk) {
    narrative.push({
      text: `Senate LDA lobbyist directory search could not be completed for “${name}” at signing time.`,
      sourceId: "lda-lobbyists-name",
    });
  } else if (lobbyistRows.length === 0) {
    narrative.push({
      text: `The Senate LDA lobbyist directory returned no entries matching the name search for “${name}” in the queried result set.`,
      sourceId: "lda-lobbyists-name",
    });
  } else {
    const sample = lobbyistRows.slice(0, 3).map((r) => {
      const ln = [r.first_name, r.last_name].filter(Boolean).join(" ");
      const reg = r.registrant?.name ?? "unknown firm";
      return `${ln} (${reg})`;
    });
    narrative.push({
      text: `The Senate LDA lobbyist directory lists ${lobbyistRows.length} entr${lobbyistRows.length === 1 ? "y" : "ies"} matching the name search for “${name}” (sample: ${sample.join("; ")}).`,
      sourceId: "lda-lobbyists-name",
    });
  }

  return {
    schemaVersion: "1.0.0",
    receiptId: crypto.randomUUID(),
    createdAt: new Date().toISOString(),
    claims: [
      {
        id: "claim-1",
        statement: `Public lobbying disclosure record for ${name}${claimSuffix}`,
        assertedAt: new Date().toISOString(),
      },
    ],
    sources,
    narrative,
    contentHash: "",
  };
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
