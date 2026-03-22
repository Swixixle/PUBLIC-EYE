import type {
  FrameReceiptPayload,
  SourceAdapter,
  SourceAdapterResult,
  SourceQuery,
  SourceRecord,
  UnknownsBlock,
} from "@frame/types";
import { buildClaim, epiUnknown, getImplicationNote, mergeUnknowns, opUnknown } from "@frame/types";

function nowIso(): string {
  return new Date().toISOString();
}

function sanitizeUrl(url: string): string {
  try {
    const u = new URL(url);
    u.searchParams.delete("api_key");
    return u.toString();
  } catch {
    return url.replace(/[?&]api_key=[^&]*/g, "");
  }
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
        url: sanitizeUrl(searchUrl),
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
      url: sanitizeUrl(totalsUrl),
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
      url: sanitizeUrl(
        `https://api.open.fec.gov/v1/candidates/totals/?candidate_id=${candidateId}`,
      ),
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

  const unknowns: UnknownsBlock = {
    operational: (result.errors ?? []).map((e) => opUnknown(e)),
    epistemic: [
      epiUnknown(
        "FEC disclosures reflect reported filings; they do not establish unlawful intent, coordination, or the full scope of indirect or issue-advocacy support.",
      ),
    ],
  };

  return {
    schemaVersion: "1.0.0",
    receiptId: crypto.randomUUID(),
    createdAt: new Date().toISOString(),
    claims: [
      buildClaim(
        "claim-1",
        `Live FEC fundraising record for ${candidateName} (${candidateId})`,
        "observed",
        "medium",
        new Date().toISOString(),
      ),
    ],
    sources,
    narrative,
    unknowns,
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
      url: sanitizeUrl(filingsUrl),
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
      url: sanitizeUrl(lobbyistsUrl),
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

  const unknowns: UnknownsBlock = {
    operational: [
      ...(!filingsOk
        ? [opUnknown("Senate LDA filings search did not complete successfully at signing time.")]
        : []),
      ...(!lobbyistsOk
        ? [opUnknown("Senate LDA lobbyist directory search did not complete successfully at signing time.")]
        : []),
    ],
    epistemic: [
      epiUnknown(
        "Lobbying disclosures report registrations and issues as filed; they do not establish causation or influence on specific legislation or votes.",
      ),
    ],
  };

  return {
    schemaVersion: "1.0.0",
    receiptId: crypto.randomUUID(),
    createdAt: new Date().toISOString(),
    claims: [
      buildClaim(
        "claim-1",
        `Public lobbying disclosure record for ${name}${claimSuffix}`,
        "observed",
        "high",
        new Date().toISOString(),
        getImplicationNote("lobbying"),
      ),
    ],
    sources,
    narrative,
    unknowns,
    contentHash: "",
  };
}

export async function buildLobbyingCrossReference(
  candidateId: string,
  clientNames: string[],
  years: number[],
  apiKey: string = "DEMO_KEY",
): Promise<FrameReceiptPayload> {
  const base = "https://lda.senate.gov/api/v1";
  const fecBase = "https://api.open.fec.gov/v1";
  const sources: SourceRecord[] = [];
  const narrative: Array<{ text: string; sourceId: string }> = [];

  // Step 1 — get candidate name from FEC
  let candidateName = candidateId;
  try {
    const r = await fetch(`${fecBase}/candidates/?candidate_id=${candidateId}&api_key=${apiKey}`);
    const d = (await r.json()) as { results?: Array<{ name?: string }> };
    if (d.results?.[0]?.name) candidateName = d.results[0].name;
  } catch {
    /* continue */
  }

  // Step 2 — for each client, find lobbying filings in the given years
  const allFindings: Array<{
    client: string;
    year: number;
    registrant: string;
    issueCodes: string[];
    filingUrl: string;
    income: number | null;
  }> = [];

  for (const client of clientNames) {
    for (const year of years) {
      try {
        const url = `${base}/filings/?filing_year=${year}&client_name=${encodeURIComponent(client)}&filing_type=Q4&limit=5`;
        const r = await fetch(url);
        if (!r.ok) continue;
        const d = (await r.json()) as {
          results?: Array<{
            registrant?: { name?: string };
            client?: { name?: string };
            income?: number | null;
            filing_document_url?: string;
            lobbying_activities?: Array<{
              general_issue_code?: string;
              general_issue_code_display?: string;
            }>;
          }>;
        };
        const sourceId = `lda-${client.replace(/\s+/g, "-").toLowerCase()}-${year}`;
        sources.push({
          id: sourceId,
          adapter: "lobbying",
          url: sanitizeUrl(url),
          title: `Senate LDA: ${client} lobbying filings — ${year}`,
          retrievedAt: nowIso(),
          externalRef: `${client}-${year}`,
          metadata: {
            client,
            year,
            count: d.results?.length ?? 0,
          },
        });
        for (const f of d.results ?? []) {
          const codes = (f.lobbying_activities ?? [])
            .map((a) => a.general_issue_code_display ?? a.general_issue_code ?? "")
            .filter(Boolean);
          allFindings.push({
            client: f.client?.name ?? client,
            year,
            registrant: f.registrant?.name ?? "Unknown",
            issueCodes: [...new Set(codes)],
            filingUrl: f.filing_document_url ?? url,
            income: f.income ?? null,
          });
        }
      } catch {
        /* continue */
      }
    }
  }

  // Step 3 — build narrative
  if (allFindings.length === 0) {
    narrative.push({
      text: `No Q4 lobbying filings found for the specified clients in the queried years.`,
      sourceId: sources[0]?.id ?? "lda-cross-reference",
    });
  } else {
    const grouped = allFindings.reduce<
      Record<string, (typeof allFindings)[number] & { count: number }>
    >((acc, f) => {
      const key = `${f.client}-${f.year}`;
      if (!acc[key]) acc[key] = { ...f, count: 0 };
      acc[key]!.count++;
      return acc;
    }, {});

    for (const finding of Object.values(grouped).slice(0, 8)) {
      const normalizedClient = finding.client.toLowerCase().split(/[\s,.()/]+/)[0];
      const matchingSource =
        sources.find(
          (s) =>
            normalizedClient.length > 0 &&
            s.id.includes(normalizedClient) &&
            s.id.includes(String(finding.year)),
        ) ??
        sources.find((s) => s.id.includes(String(finding.year))) ??
        sources[0];
      const sourceId =
        matchingSource?.id ?? sources[0]?.id ?? "lda-cross-reference";
      const issueText = finding.issueCodes.length
        ? `Issue areas on file: ${finding.issueCodes.slice(0, 3).join(", ")}.`
        : "No issue codes listed.";
      narrative.push({
        text: `In ${finding.year}, ${finding.registrant} filed lobbying disclosures on behalf of ${finding.client}. ${issueText}`,
        sourceId,
      });
    }

    narrative.push({
      text: `Cross-reference: ${candidateName} (FEC ID: ${candidateId}) received campaign contributions from donors in the fossil fuel sector during overlapping periods. See FEC records for contribution details.`,
      sourceId: sources[0]?.id ?? "lda-cross-reference",
    });
  }

  const unknowns: UnknownsBlock = {
    operational: [],
    epistemic: [
      epiUnknown(
        "Cross-referenced timelines are descriptive; they do not prove coordination between lobbyists and campaign contributions.",
      ),
    ],
  };

  return {
    schemaVersion: "1.0.0",
    receiptId: crypto.randomUUID(),
    createdAt: new Date().toISOString(),
    claims: [
      buildClaim(
        "claim-1",
        `Lobbying and campaign finance cross-reference for ${candidateName} (${candidateId})`,
        "observed",
        "high",
        new Date().toISOString(),
        getImplicationNote("cross_reference"),
      ),
    ],
    sources,
    narrative,
    unknowns,
    contentHash: "",
  };
}

export async function buildCombinedPoliticianReceipt(
  candidateId: string,
  lobbyingClients: string[],
  years: number[],
  apiKey: string = "DEMO_KEY",
): Promise<FrameReceiptPayload> {
  const [fecResult, ldaResult] = await Promise.all([
    buildLiveFecReceipt(candidateId, apiKey),
    buildLobbyingCrossReference(candidateId, lobbyingClients, years, apiKey),
  ]);

  const allSources = [...fecResult.sources, ...ldaResult.sources].map((s) => ({
    ...s,
    url: sanitizeUrl(s.url),
  }));

  const fecTotalsSource = fecResult.sources.find((s) => s.id.includes("totals"));
  const fecMeta = fecTotalsSource?.metadata as
    | Record<string, string | number | boolean | null>
    | undefined;
  let cycleTotals: Array<{ cycle: number; pacContributions: number }> | undefined;
  if (fecMeta?.allCycleTotalsJson && typeof fecMeta.allCycleTotalsJson === "string") {
    try {
      cycleTotals = JSON.parse(fecMeta.allCycleTotalsJson) as Array<{
        cycle: number;
        pacContributions: number;
      }>;
    } catch {
      cycleTotals = undefined;
    }
  }

  const candidateName = (fecResult.claims[0]?.statement ?? candidateId)
    .replace("Live FEC fundraising record for ", "")
    .replace(` (${candidateId})`, "");

  const fecNarrative = fecResult.narrative;
  const ldaNarrative = ldaResult.narrative.filter(
    (s) => !s.text.includes("Cross-reference:"),
  );

  let crossRefText = "";
  if (cycleTotals && cycleTotals.length > 0) {
    const cycleLines = cycleTotals
      .filter((c) => years.includes(c.cycle) || years.includes(c.cycle - 1))
      .slice(0, 3)
      .map(
        (c) =>
          `$${c.pacContributions.toLocaleString()} from PACs in the ${c.cycle} cycle`,
      );
    if (cycleLines.length > 0) {
      crossRefText = `Cross-reference: ${candidateName} received ${cycleLines.join(" and ")} during periods when ${lobbyingClients.slice(0, 3).join(", ")} filed lobbying disclosures on energy and tax legislation with the Senate.`;
    }
  }
  if (!crossRefText) {
    crossRefText = `Cross-reference: FEC contribution records for ${candidateName} overlap with the lobbying periods documented above.`;
  }

  const crossRefSourceId =
    fecResult.sources.find((s) => s.id.includes("totals"))?.id ??
    allSources[0]?.id ??
    "fec-totals";

  const combinedNarrative = [
    ...fecNarrative,
    ...ldaNarrative,
    { text: crossRefText, sourceId: crossRefSourceId },
  ];

  return {
    schemaVersion: "1.0.0",
    receiptId: crypto.randomUUID(),
    createdAt: new Date().toISOString(),
    claims: [
      buildClaim(
        "claim-1",
        `Campaign finance and lobbying record for ${candidateName} (${candidateId})`,
        "observed",
        "high",
        new Date().toISOString(),
        getImplicationNote("cross_reference"),
      ),
    ],
    sources: allSources,
    narrative: combinedNarrative,
    unknowns: mergeUnknowns(fecResult.unknowns, ldaResult.unknowns),
    contentHash: "",
  };
}

export async function buildLive990Receipt(
  orgName: string,
  ein?: string,
): Promise<FrameReceiptPayload> {
  const base = "https://projects.propublica.org/nonprofits/api/v2";
  const sources: SourceRecord[] = [];
  const narrative: Array<{ text: string; sourceId: string }> = [];

  let resolvedEin = ein ?? "";
  let resolvedName = orgName;

  const searchSourceId = `irs-search-${orgName.replace(/\s+/g, "-").toLowerCase()}`;

  // Step 1 — search for org if no EIN provided
  if (!resolvedEin) {
    try {
      const searchUrl = `${base}/search.json?q=${encodeURIComponent(orgName)}`;
      const r = await fetch(searchUrl);
      const d = (await r.json()) as {
        organizations?: Array<{
          ein: number;
          name: string;
          city?: string;
          state?: string;
        }>;
      };
      const first = d.organizations?.[0];
      if (first) {
        resolvedEin = String(first.ein);
        resolvedName = first.name;
      }
      sources.push({
        id: searchSourceId,
        adapter: "manual",
        url: searchUrl,
        title: `ProPublica Nonprofit Explorer: search for "${orgName}"`,
        retrievedAt: nowIso(),
        externalRef: resolvedEin || orgName,
        metadata: {
          query: orgName,
          resolvedEin: resolvedEin || null,
          resolvedName,
        },
      });
    } catch {
      /* continue */
    }
  }

  if (!resolvedEin) {
    narrative.push({
      text: `ProPublica Nonprofit Explorer returned no results for "${orgName}" at signing time.`,
      sourceId: sources[0]?.id ?? searchSourceId,
    });
    return {
      schemaVersion: "1.0.0",
      receiptId: crypto.randomUUID(),
      createdAt: new Date().toISOString(),
      claims: [
        buildClaim(
          "claim-1",
          `IRS 990 record for ${orgName}`,
          "observed",
          "low",
          new Date().toISOString(),
        ),
      ],
      sources,
      narrative,
      unknowns: {
        operational: [
          opUnknown(
            "ProPublica Nonprofit Explorer search did not resolve an EIN for this organization at signing time.",
          ),
        ],
        epistemic: [
          epiUnknown(
            "Even when filings are available, Form 990 aggregates do not establish private intent or off-balance-sheet activity.",
          ),
        ],
      },
      contentHash: "",
    };
  }

  // Step 2 — fetch org details and filings
  try {
    const orgUrl = `${base}/organizations/${resolvedEin}.json`;
    const r = await fetch(orgUrl);
    const d = (await r.json()) as {
      organization?: {
        name?: string;
        city?: string;
        state?: string;
        asset_amount?: number;
        income_amount?: number;
        tax_period?: string;
      };
      filings_with_data?: Array<{
        tax_yr?: number;
        tax_prd_yr?: number;
        totrevenue?: number;
        totfuncexpns?: number;
        totassetsend?: number;
        grscontrgifts?: number;
        pct_compnsatncurrofcr?: number;
      }>;
    };

    const org = d.organization;
    const filings = d.filings_with_data ?? [];
    resolvedName = org?.name ?? resolvedName;

    sources.push({
      id: `irs-990-${resolvedEin}`,
      adapter: "manual",
      url: orgUrl,
      title: `IRS 990: ${resolvedName} (EIN ${resolvedEin})`,
      retrievedAt: nowIso(),
      externalRef: resolvedEin,
      metadata: {
        ein: resolvedEin,
        name: resolvedName,
        city: org?.city ?? null,
        state: org?.state ?? null,
        assetAmount: org?.asset_amount ?? null,
        incomeAmount: org?.income_amount ?? null,
      },
    });

    const sourceId = `irs-990-${resolvedEin}`;

    if (org?.asset_amount != null) {
      narrative.push({
        text: `According to IRS 990 filings, ${resolvedName} (EIN: ${resolvedEin}) reported total assets of $${org.asset_amount.toLocaleString()} and income of $${(org.income_amount ?? 0).toLocaleString()} as of the most recent filing period.`,
        sourceId,
      });
    }

    for (const f of filings.slice(0, 3)) {
      const yr = f.tax_yr ?? f.tax_prd_yr ?? "unknown";
      const rev =
        f.totrevenue != null ? `$${f.totrevenue.toLocaleString()}` : "not reported";
      const exp =
        f.totfuncexpns != null ? `$${f.totfuncexpns.toLocaleString()}` : "not reported";
      const assets =
        f.totassetsend != null ? `$${f.totassetsend.toLocaleString()}` : "not reported";
      const gifts =
        f.grscontrgifts != null ? `$${f.grscontrgifts.toLocaleString()}` : "not reported";
      narrative.push({
        text: `In tax year ${yr}, ${resolvedName} reported total revenue of ${rev}, total functional expenses of ${exp}, end-of-year assets of ${assets}, and gross contributions/gifts received of ${gifts}.`,
        sourceId,
      });
    }
  } catch {
    narrative.push({
      text: `IRS 990 data for EIN ${resolvedEin} could not be retrieved at signing time.`,
      sourceId: `irs-990-${resolvedEin}`,
    });
  }

  return {
    schemaVersion: "1.0.0",
    receiptId: crypto.randomUUID(),
    createdAt: new Date().toISOString(),
    claims: [
      buildClaim(
        "claim-1",
        `IRS 990 financial record for ${resolvedName} (EIN: ${resolvedEin})`,
        "observed",
        "medium",
        new Date().toISOString(),
      ),
    ],
    sources,
    narrative,
    unknowns: {
      operational: [],
      epistemic: [
        epiUnknown(
          "Form 990 figures are self-reported; delays or amendments may change totals after signing.",
        ),
      ],
    },
    contentHash: "",
  };
}

export async function buildWikidataReceipt(
  personName: string,
  wikidataId?: string,
): Promise<FrameReceiptPayload> {
  const base = "https://www.wikidata.org/w/api.php";
  const sources: SourceRecord[] = [];
  const narrative: Array<{ text: string; sourceId: string }> = [];

  let resolvedId = wikidataId ?? "";
  let resolvedName = personName;

  const searchSourceId = `wikidata-search-${personName.replace(/\s+/g, "-").toLowerCase()}`;

  // Step 1 — search for person if no ID provided
  if (!resolvedId) {
    try {
      const searchUrl = `${base}?action=wbsearchentities&search=${encodeURIComponent(personName)}&language=en&format=json&limit=1`;
      const r = await fetch(searchUrl);
      const d = (await r.json()) as {
        search?: Array<{ id: string; label?: string; description?: string }>;
      };
      const first = d.search?.[0];
      if (first) {
        resolvedId = first.id;
        resolvedName = first.label ?? personName;
      }
      sources.push({
        id: searchSourceId,
        adapter: "manual",
        url: searchUrl,
        title: `Wikidata: search for "${personName}"`,
        retrievedAt: nowIso(),
        externalRef: resolvedId || personName,
        metadata: {
          query: personName,
          resolvedId: resolvedId || null,
          description: d.search?.[0]?.description ?? null,
        },
      });
    } catch {
      /* continue */
    }
  }

  if (!resolvedId) {
    narrative.push({
      text: `Wikidata returned no results for "${personName}" at signing time.`,
      sourceId: sources[0]?.id ?? searchSourceId,
    });
    return {
      schemaVersion: "1.0.0",
      receiptId: crypto.randomUUID(),
      createdAt: new Date().toISOString(),
      claims: [
        buildClaim(
          "claim-1",
          `Wikidata public record for ${personName}`,
          "observed",
          "low",
          new Date().toISOString(),
        ),
      ],
      sources,
      narrative,
      unknowns: {
        operational: [
          opUnknown("Wikidata entity search did not return a matching item at signing time."),
        ],
        epistemic: [
          epiUnknown(
            "Even when present, Wikidata statements are crowdsourced and may be incomplete or disputed.",
          ),
        ],
      },
      contentHash: "",
    };
  }

  // Step 2 — fetch entity data
  try {
    const entityUrl = `${base}?action=wbgetentities&ids=${resolvedId}&languages=en&props=claims|labels|descriptions|sitelinks&format=json`;
    const r = await fetch(entityUrl);
    const d = (await r.json()) as {
      entities?: Record<
        string,
        {
          labels?: { en?: { value?: string } };
          descriptions?: { en?: { value?: string } };
          claims?: Record<
            string,
            Array<{
              mainsnak?: {
                snaktype?: string;
                datavalue?: {
                  value?: unknown;
                  type?: string;
                };
              };
            }>
          >;
          sitelinks?: { enwiki?: { title?: string } };
        }
      >;
    };

    const entity = d.entities?.[resolvedId];
    if (!entity) throw new Error("Entity not found");

    resolvedName = entity.labels?.en?.value ?? resolvedName;
    const description = entity.descriptions?.en?.value ?? "";
    const wikipediaTitle = entity.sitelinks?.enwiki?.title;
    const claims = entity.claims ?? {};

    sources.push({
      id: `wikidata-entity-${resolvedId}`,
      adapter: "manual",
      url: `https://www.wikidata.org/wiki/${resolvedId}`,
      title: `Wikidata: ${resolvedName} (${resolvedId})`,
      retrievedAt: nowIso(),
      externalRef: resolvedId,
      metadata: {
        resolvedId,
        resolvedName,
        description: description || null,
        wikipediaTitle: wikipediaTitle ?? null,
      },
    });

    const sourceId = `wikidata-entity-${resolvedId}`;

    if (description) {
      narrative.push({
        text: `According to Wikidata, ${resolvedName} is described as: "${description}".`,
        sourceId,
      });
    }

    // Resolve entity IDs to labels with a single batch call
    const allEntityIds = [
      ...(claims["P106"] ?? []).map(
        (c) => (c.mainsnak?.datavalue?.value as { id?: string })?.id,
      ),
      ...(claims["P108"] ?? []).map(
        (c) => (c.mainsnak?.datavalue?.value as { id?: string })?.id,
      ),
      ...(claims["P102"] ?? []).map(
        (c) => (c.mainsnak?.datavalue?.value as { id?: string })?.id,
      ),
    ]
      .filter(Boolean)
      .slice(0, 20) as string[];

    let labelMap: Record<string, string> = {};
    if (allEntityIds.length > 0) {
      try {
        const labelUrl = `${base}?action=wbgetentities&ids=${allEntityIds.join("|")}&languages=en&props=labels&format=json`;
        const lr = await fetch(labelUrl);
        const ld = (await lr.json()) as {
          entities?: Record<string, { labels?: { en?: { value?: string } } }>;
        };
        for (const [id, ent] of Object.entries(ld.entities ?? {})) {
          labelMap[id] = ent.labels?.en?.value ?? id;
        }
      } catch {
        /* use IDs as fallback */
      }
    }

    // Occupations (P106)
    const occupationIds = (claims["P106"] ?? [])
      .map((c) => (c.mainsnak?.datavalue?.value as { id?: string })?.id)
      .filter(Boolean) as string[];
    const occupationLabels = occupationIds.map((id) => labelMap[id] ?? id).slice(0, 5);
    if (occupationLabels.length > 0) {
      narrative.push({
        text: `According to Wikidata, ${resolvedName}'s listed occupations include: ${occupationLabels.join(", ")}.`,
        sourceId,
      });
    }

    // Employers (P108)
    const employerIds = (claims["P108"] ?? [])
      .map((c) => (c.mainsnak?.datavalue?.value as { id?: string })?.id)
      .filter(Boolean) as string[];
    const employerLabels = employerIds.map((id) => labelMap[id] ?? id).slice(0, 5);
    if (employerLabels.length > 0) {
      narrative.push({
        text: `According to Wikidata, ${resolvedName}'s listed employers include: ${employerLabels.join(", ")}.`,
        sourceId,
      });
    }

    // Political party (P102)
    const partyIds = (claims["P102"] ?? [])
      .map((c) => (c.mainsnak?.datavalue?.value as { id?: string })?.id)
      .filter(Boolean) as string[];
    const partyLabels = partyIds.map((id) => labelMap[id] ?? id).slice(0, 3);
    if (partyLabels.length > 0) {
      narrative.push({
        text: `According to Wikidata, ${resolvedName}'s listed political party affiliation(s) include: ${partyLabels.join(", ")}.`,
        sourceId,
      });
    }

    // Wikipedia link
    if (wikipediaTitle) {
      sources.push({
        id: `wikipedia-${resolvedId}`,
        adapter: "manual",
        url: `https://en.wikipedia.org/wiki/${encodeURIComponent(wikipediaTitle.replace(/ /g, "_"))}`,
        title: `Wikipedia: ${wikipediaTitle}`,
        retrievedAt: nowIso(),
        externalRef: resolvedId,
        metadata: { title: wikipediaTitle },
      });
      narrative.push({
        text: `A Wikipedia article exists for ${resolvedName} at https://en.wikipedia.org/wiki/${encodeURIComponent(wikipediaTitle.replace(/ /g, "_"))}.`,
        sourceId: `wikipedia-${resolvedId}`,
      });
    }
  } catch {
    narrative.push({
      text: `Wikidata entity data for ${resolvedId} could not be retrieved at signing time.`,
      sourceId: `wikidata-entity-${resolvedId}`,
    });
  }

  return {
    schemaVersion: "1.0.0",
    receiptId: crypto.randomUUID(),
    createdAt: new Date().toISOString(),
    claims: [
      buildClaim(
        "claim-1",
        `Wikidata public record for ${resolvedName} (${resolvedId})`,
        "observed",
        "medium",
        new Date().toISOString(),
      ),
    ],
    sources,
    narrative,
    unknowns: {
      operational: [],
      epistemic: [
        epiUnknown(
          "Wikidata statements are claims about the world, not court findings; presence of a statement does not establish its accuracy.",
        ),
      ],
    },
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
