import type {
  NarrativeSentence,
  NarrativeViolation,
  SourceRecord,
} from "@frame/types";

/**
 * Judgment adjectives and related terms are banned from Frame narrative text.
 * Frame describes filings, votes, and money with neutral language only.
 */
export const BANNED_WORDS: readonly string[] = [
  "corrupt",
  "corruption",
  "suspicious",
  "troubling",
  "criminal",
  "fraud",
  "fraudulent",
  "unethical",
  "scandal",
  "scandalous",
  "shady",
  "crooked",
  "bribe",
  "bribery",
  "sleazy",
  "disgraceful",
  "nefarious",
  "evil",
  "vile",
];

/**
 * Only these hostnames (or subdomains) are accepted in `SourceRecord.url`.
 * Adjust per deployment; wildcards are not supported — list concrete hosts.
 */
export const DOMAIN_WHITELIST: readonly string[] = [
  "www.fec.gov",
  "api.open.fec.gov",
  "www.opensecrets.org",
  "www.propublica.org",
  "projects.propublica.org",
  "lda.senate.gov",
  "efdsearch.senate.gov",
  "disclosures.house.gov",
  "www.sec.gov",
  "www.congress.gov",
  "data.gov",
];

function hostnameOf(url: string): string | null {
  try {
    const u = new URL(url);
    return u.hostname.toLowerCase();
  } catch {
    return null;
  }
}

function isWhitelistedHost(hostname: string): boolean {
  return DOMAIN_WHITELIST.some(
    (allowed) => hostname === allowed || hostname.endsWith(`.${allowed}`),
  );
}

function findBannedToken(text: string): string | undefined {
  const lower = text.toLowerCase();
  for (const word of BANNED_WORDS) {
    const re = new RegExp(`\\b${escapeRegExp(word)}\\b`, "i");
    if (re.test(lower)) return word;
  }
  return undefined;
}

function escapeRegExp(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

const sourceIds = (sources: SourceRecord[]): Set<string> =>
  new Set(sources.map((s) => s.id));

/**
 * Validates narrative sentences against Frame rules:
 * 1. Every sentence references a `sourceId` present in `sources`.
 * 2. No banned judgment language.
 * 3. Every cited source URL uses a whitelisted domain.
 */
export function validateNarrative(
  narrative: NarrativeSentence[],
  sources: SourceRecord[],
): NarrativeViolation[] {
  const violations: NarrativeViolation[] = [];
  const ids = sourceIds(sources);
  const sourceById = new Map(sources.map((s) => [s.id, s] as const));

  narrative.forEach((sentence, sentenceIndex) => {
    if (!sentence.sourceId || sentence.sourceId.trim() === "") {
      violations.push({
        code: "MISSING_SOURCE_ID",
        message: "Narrative sentence is missing sourceId.",
        sentenceIndex,
      });
      return;
    }
    if (!ids.has(sentence.sourceId)) {
      violations.push({
        code: "UNKNOWN_SOURCE_ID",
        message: `sourceId "${sentence.sourceId}" is not in the sources array.`,
        sentenceIndex,
      });
    }

    const banned = findBannedToken(sentence.text);
    if (banned) {
      violations.push({
        code: "BANNED_LANGUAGE",
        message: "Narrative contains banned judgment language.",
        sentenceIndex,
        token: banned,
      });
    }
  });

  for (const s of sources) {
    const host = hostnameOf(s.url);
    if (!host || !isWhitelistedHost(host)) {
      violations.push({
        code: "DOMAIN_NOT_WHITELISTED",
        message: `Source "${s.id}" URL host is not whitelisted: ${s.url}`,
      });
    }
  }

  // If unknown source id, we already flagged; still check domain for known sources
  for (const sentence of narrative) {
    const src = sourceById.get(sentence.sourceId);
    if (!src) continue;
    const host = hostnameOf(src.url);
    if (!host || !isWhitelistedHost(host)) {
      violations.push({
        code: "DOMAIN_NOT_WHITELISTED",
        message: `Narrative cites source "${sentence.sourceId}" with non-whitelisted URL.`,
      });
    }
  }

  return violations;
}
