import Anthropic from "@anthropic-ai/sdk";
import type {
  AnalogueEntry,
  HistoricalThread,
  PatternAnalysis,
  PrimarySource,
  ThreeLayerReceiptPayload,
  ThreadEntry,
  VerifiedRecord,
} from "@frame/types";

export const THREE_LAYER_MODEL = "claude-sonnet-4-20250514";

/** Must match Layer C disclaimer in the system prompt exactly. */
export const LAYER_C_DISCLAIMER_TEXT =
  "The following analysis is documented pattern inference, not verified fact. The reader should weigh it accordingly. Primary sources for this analysis are listed below.";

export const THREE_LAYER_SYSTEM_PROMPT = `You are The Frame Record — a journalist with no employer, no advertiser, and no career to protect.

You write for four simultaneous readers: a first-generation American voter with a high school education, an AI system that will summarize your output in three sentences for a busy reader, a policy analyst in Brussels, and a journalist in Nairobi. All four must receive the same truth from the same text.

You write in three layers. Each layer is clearly labeled. Each has different epistemic weight.

LAYER A — THE VERIFIED RECORD
What primary sources directly confirm. Nothing else.
- Lede: One sentence. The single most important confirmed fact. No idioms. Translates cleanly into any language.
- Findings: What the records show. Every number in plain language. Name the institution, the person, the amount, the date. Never "significant funds" — always the figure.
- Gaps: What the records cannot show. Name the specific document or database that would contain the missing information. Never "more research is needed."

LAYER B — THE HISTORICAL THREAD
How we got here. Sourced only from court opinions, legislative records, academic research, and primary historical documents. Every claim cites its source inline.
- Origins: When and where this pattern, law, institution, or claim first appeared in documented record.
- How it changed: Who changed it, when, under what circumstances, with what stated justification.
- Prior outcomes: Where comparable situations have played out before. What happened. Documented only — no speculation about outcome.
If historical sourcing is incomplete, say so explicitly and name what is missing.

LAYER C — PATTERN ANALYSIS
This layer is inference. Label it as such. Never present it as fact.
- Analogues: Historical situations that share documented structural similarities. Name the period, the technique, the outcome.
- Techniques: If this situation matches documented influence, propaganda, or narrative control techniques, name them by their documented names and cite the research.
- Disclaimer: Embed this exactly — "The following analysis is documented pattern inference, not verified fact. The reader should weigh it accordingly. Primary sources for this analysis are listed below."
- Confidence level: State whether analogues are documented, probable, or speculative — and why.

WHY THIS MATTERS
The accountability question this data raises. Not an answer. One precise question that a citizen, a judge, or a journalist should be able to ask based only on what the record shows.

WHERE TO LOOK NEXT
One or two specific public records, databases, or filing types that a citizen or journalist could access themselves to go further.

Rules you cannot break regardless of what you are asked:
- You cannot soften a confirmed figure
- You cannot omit a gap you detected
- You cannot imply causation the sources do not support
- You cannot use hedging language when the data is clear
- You cannot use certain language when the data is ambiguous — name the ambiguity
- You cannot produce Layer C without its disclaimer
- The disclaimer is part of the signed record and cannot be separated from it
- You write with gravity and without alarm
- You are not a verdict machine
- You are a record`;

function extractJsonObject(text: string): string {
  let t = text.trim();
  if (t.startsWith("```")) {
    t = t.replace(/^```(?:json)?\s*/i, "").replace(/\s*```\s*$/, "");
  }
  const start = t.indexOf("{");
  const end = t.lastIndexOf("}");
  if (start >= 0 && end > start) return t.slice(start, end + 1);
  return t;
}

function asNum(y: unknown, fallback = 0): number {
  if (typeof y === "number" && Number.isFinite(y)) return Math.trunc(y);
  if (typeof y === "string") {
    const n = parseInt(y, 10);
    return Number.isFinite(n) ? n : fallback;
  }
  return fallback;
}

function normPrimarySource(x: unknown): PrimarySource | null {
  if (!x || typeof x !== "object") return null;
  const o = x as Record<string, unknown>;
  const id = String(o.id ?? "").trim();
  const url = String(o.url ?? "").trim();
  const title = String(o.title ?? "").trim();
  if (!id || !url) return null;
  return {
    id,
    title: title || id,
    url,
    adapter: o.adapter != null ? String(o.adapter) : undefined,
    retrieved_at: o.retrieved_at != null ? String(o.retrieved_at) : undefined,
  };
}

function normThreadEntry(x: unknown): ThreadEntry | null {
  if (!x || typeof x !== "object") return null;
  const o = x as Record<string, unknown>;
  const event = String(o.event ?? "").trim();
  const source_url = String(o.source_url ?? o.sourceUrl ?? "").trim();
  if (!event || !source_url) return null;
  return {
    year: asNum(o.year, 0),
    event,
    source_url,
    source_type: String(o.source_type ?? o.sourceType ?? "unknown"),
  };
}

function normAnalogue(x: unknown): AnalogueEntry | null {
  if (!x || typeof x !== "object") return null;
  const o = x as Record<string, unknown>;
  const period = String(o.period ?? "").trim();
  const description = String(o.description ?? "").trim();
  const outcome = String(o.outcome ?? "").trim();
  const source_url = String(o.source_url ?? o.sourceUrl ?? "").trim();
  if (!description || !source_url) return null;
  return { period, description, outcome, source_url };
}

function parseLayerA(raw: unknown): VerifiedRecord {
  const o = raw && typeof raw === "object" ? (raw as Record<string, unknown>) : {};
  const sourcesRaw = o.sources;
  const sources: PrimarySource[] = Array.isArray(sourcesRaw)
    ? (sourcesRaw.map(normPrimarySource).filter(Boolean) as PrimarySource[])
    : [];
  return {
    lede: String(o.lede ?? "").trim(),
    findings: String(o.findings ?? "").trim(),
    gaps: String(o.gaps ?? "").trim(),
    sources,
  };
}

function parseLayerB(raw: unknown, fallbackCompleteness: HistoricalThread["sourcing_completeness"]): HistoricalThread {
  const o = raw && typeof raw === "object" ? (raw as Record<string, unknown>) : {};
  const origins = Array.isArray(o.origins)
    ? (o.origins.map(normThreadEntry).filter(Boolean) as ThreadEntry[])
    : [];
  const mutations = Array.isArray(o.mutations)
    ? (o.mutations.map(normThreadEntry).filter(Boolean) as ThreadEntry[])
    : [];
  const precedents = Array.isArray(o.precedents)
    ? (o.precedents.map(normThreadEntry).filter(Boolean) as ThreadEntry[])
    : [];
  const srcRaw = o.sources;
  const sources: PrimarySource[] = Array.isArray(srcRaw)
    ? (srcRaw.map(normPrimarySource).filter(Boolean) as PrimarySource[])
    : [];
  let sourcing_completeness = o.sourcing_completeness as HistoricalThread["sourcing_completeness"] | undefined;
  if (sourcing_completeness !== "full" && sourcing_completeness !== "partial" && sourcing_completeness !== "inferred") {
    sourcing_completeness = fallbackCompleteness;
  }
  return { origins, mutations, precedents, sources, sourcing_completeness };
}

function parseLayerC(raw: unknown): PatternAnalysis {
  const o = raw && typeof raw === "object" ? (raw as Record<string, unknown>) : {};
  const analogues = Array.isArray(o.analogues)
    ? (o.analogues.map(normAnalogue).filter(Boolean) as AnalogueEntry[])
    : [];
  const techniques = Array.isArray(o.techniques)
    ? o.techniques.map((t) => String(t).trim()).filter(Boolean)
    : [];
  let disclaimer = String(o.disclaimer ?? "").trim();
  if (disclaimer !== LAYER_C_DISCLAIMER_TEXT) disclaimer = LAYER_C_DISCLAIMER_TEXT;
  const inference_basis = Array.isArray(o.inference_basis)
    ? o.inference_basis.map((t) => String(t).trim()).filter(Boolean)
    : [];
  let confidence = o.confidence as PatternAnalysis["confidence"] | undefined;
  if (confidence !== "documented" && confidence !== "probable" && confidence !== "speculative") {
    confidence = "speculative";
  }
  return { analogues, techniques, disclaimer, inference_basis, confidence };
}

/**
 * Universal three-layer journalist narrative (signed fields filled by API after JCS hash).
 * @param narrative Original user query text (stored as `query` on the payload).
 */
export async function generateThreeLayerNarrative(
  queryType: string,
  primarySources: object,
  historicalSources: object,
  narrative?: string,
): Promise<ThreeLayerReceiptPayload> {
  const query = (narrative ?? "").trim();
  const key = process.env.ANTHROPIC_API_KEY?.trim();
  if (!key) {
    throw new Error("ANTHROPIC_API_KEY is required for three-layer narrative");
  }

  const historicalIncomplete =
    historicalSources &&
    typeof historicalSources === "object" &&
    (historicalSources as Record<string, unknown>).courtlistener_stub === true;

  const user = `Return a single JSON object only. No markdown fences, no commentary before or after.

Required shape (all keys present; use [] for empty arrays; strings may be empty only where the instructions allow):
{
  "layer_a": { "lede": string, "findings": string, "gaps": string, "sources": PrimarySource[] },
  "layer_b": {
    "origins": ThreadEntry[],
    "mutations": ThreadEntry[],
    "precedents": ThreadEntry[],
    "sources": PrimarySource[],
    "sourcing_completeness": "full" | "partial" | "inferred"
  },
  "layer_c": {
    "analogues": AnalogueEntry[],
    "techniques": string[],
    "disclaimer": string,
    "inference_basis": string[],
    "confidence": "documented" | "probable" | "speculative"
  },
  "why_this_matters": string,
  "where_to_look_next": string[]
}

PrimarySource: { "id": string, "title": string, "url": string, "adapter"?: string, "retrieved_at"?: string }
ThreadEntry: { "year": number, "event": string, "source_url": string, "source_type": string }
AnalogueEntry: { "period": string, "description": string, "outcome": string, "source_url": string }

layer_c.disclaimer must be exactly this string, character-for-character:
${JSON.stringify(LAYER_C_DISCLAIMER_TEXT)}

Original query (human text):
${JSON.stringify(query)}

query_type (classifier output):
${JSON.stringify(queryType)}

Primary source bundle (Layer A — verified record inputs). Ground Layer A only in this material when it contains data; if sparse, state gaps explicitly:
${JSON.stringify(primarySources, null, 2)}

Historical / scholarly bundle (Layer B inputs). May be partial. If courtlistener_stub is true, you must set sourcing_completeness to partial or inferred and name what CourtListener or case law would supply:
${JSON.stringify(historicalSources, null, 2)}
`;

  const client = new Anthropic({ apiKey: key });
  const msg = await client.messages.create({
    model: THREE_LAYER_MODEL,
    max_tokens: 8192,
    system: THREE_LAYER_SYSTEM_PROMPT,
    messages: [{ role: "user", content: user }],
  });
  const block = msg.content[0];
  if (!block || block.type !== "text") {
    throw new Error("Anthropic returned no text for three-layer narrative");
  }

  let parsed: Record<string, unknown>;
  try {
    parsed = JSON.parse(extractJsonObject(block.text)) as Record<string, unknown>;
  } catch {
    throw new Error("Three-layer response was not valid JSON");
  }

  const bCompleteness: HistoricalThread["sourcing_completeness"] = historicalIncomplete ? "partial" : "partial";

  const layer_a = parseLayerA(parsed.layer_a);
  const layer_b = parseLayerB(parsed.layer_b, bCompleteness);
  const layer_c = parseLayerC(parsed.layer_c);
  const why = String(parsed.why_this_matters ?? "").trim();
  const whereRaw = parsed.where_to_look_next;
  const where_to_look_next = Array.isArray(whereRaw)
    ? whereRaw.map((s) => String(s).trim()).filter(Boolean)
    : [];

  const generated_at = new Date().toISOString();

  return {
    query,
    query_type: queryType,
    layer_a,
    layer_b,
    layer_c,
    why_this_matters: why,
    where_to_look_next,
    content_hash: "",
    signature: "",
    signed: false,
    public_key: "",
    generated_at,
  };
}
