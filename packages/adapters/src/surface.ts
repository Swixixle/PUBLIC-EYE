import Anthropic from "@anthropic-ai/sdk";
import type { DepthLayer, SurfaceResult } from "@frame/types";
import { ConfidenceTier, DEPTH_LAYER_SURFACE } from "@frame/types";

const MODEL =
  process.env.ANTHROPIC_SURFACE_MODEL?.trim() || "claude-3-5-sonnet-20241022";

const TIER_VALUES = new Set<string>(Object.values(ConfidenceTier));

function asTier(raw: unknown, fallback: ConfidenceTier): ConfidenceTier {
  if (typeof raw === "string" && TIER_VALUES.has(raw)) {
    return raw as ConfidenceTier;
  }
  return fallback;
}

function extractJsonObject(text: string): string {
  let t = text.trim();
  if (t.startsWith("```")) {
    t = t.replace(/^```(?:json)?\s*/i, "").replace(/\s*```\s*$/, "");
  }
  const start = t.indexOf("{");
  const end = t.lastIndexOf("}");
  if (start >= 0 && end > start) {
    return t.slice(start, end + 1);
  }
  return t;
}

function stripHtmlToText(html: string): string {
  return html
    .replace(/<script[\s\S]*?<\/script>/gi, " ")
    .replace(/<style[\s\S]*?<\/style>/gi, " ")
    .replace(/<[^>]+>/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

async function fetchUrlNarrative(url: string): Promise<{ text: string; ok: boolean }> {
  const res = await fetch(url, {
    headers: { "User-Agent": "Frame-SurfaceAdapter/1.0" },
    redirect: "follow",
  });
  const raw = await res.text();
  const text = stripHtmlToText(raw).slice(0, 80_000);
  return { text, ok: res.ok };
}

/** Static Layer 1 metadata (depth map). */
export async function getSurfaceDepthLayer(): Promise<DepthLayer> {
  return { ...DEPTH_LAYER_SURFACE };
}

/**
 * Layer 1 extraction: narrative or URL → structured surface record (Anthropic JSON only).
 */
export async function getSurfaceLayer(input: {
  narrative?: string;
  url?: string;
}): Promise<SurfaceResult> {
  const n = input.narrative?.trim();
  const u = input.url?.trim();
  if (n && u) {
    throw new Error("Provide exactly one of narrative or url");
  }
  if (!n && !u) {
    throw new Error("Provide exactly one of narrative or url");
  }

  const key = process.env.ANTHROPIC_API_KEY?.trim();
  if (!key) {
    throw new Error("ANTHROPIC_API_KEY is required for surface extraction");
  }

  let narrativeBody: string;
  let sourceUrl: string | null;
  let sourceUrlTier: ConfidenceTier | null;

  if (u) {
    sourceUrl = u;
    const { text, ok } = await fetchUrlNarrative(u);
    narrativeBody = text || "(empty body)";
    sourceUrlTier = ok ? ConfidenceTier.OfficialSecondary : ConfidenceTier.SingleSource;
  } else {
    sourceUrl = null;
    sourceUrlTier = null;
    narrativeBody = n!;
  }

  const tierList = Array.from(TIER_VALUES).join(", ");

  const urlInstructions = sourceUrl
    ? `- source_url must be exactly: ${JSON.stringify(sourceUrl)}
- source_url_confidence_tier: string, one of: ${tierList} (how confident the URL identity and fetch are)`
    : `- source_url: null
- source_url_confidence_tier: null`;

  const prompt = `You are a neutral forensic auditor. The input is source text (possibly from a web page). Extract Layer 1 (Surface) facts only — no verdict, no moral judgment, no spin.

Return a single JSON object with EXACTLY these keys (no markdown, no prose outside JSON):
- what: string — one paragraph plain-language description of the main claim or subject matter.
- what_confidence_tier: string — one of: ${tierList}
- who: array of objects, each { "name": string, "confidence_tier": string } — named actors (people, organizations, forums) mentioned; use empty array if none.
- when: object { "earliest_appearance": string, "source": string, "confidence_tier": string } — earliest datable appearance described; if unknown, use best-effort strings and list "when" in absent_fields.
${urlInstructions}
- absent_fields: array of strings — each must be one of: "what", "who", "when", "source_url" — listing which of those logical fields could not be populated from the input. Use [] only if all four were populated. Never omit absent_fields.

Rules:
- confidence_tier values must be exactly from the list above.
- If the text does not support a field, still return the key with empty or best-effort content AND include the field name in absent_fields.

Source text:
---
${narrativeBody}
---
`;

  const client = new Anthropic({ apiKey: key });
  let msg: Awaited<ReturnType<Anthropic["messages"]["create"]>>;
  try {
    msg = await client.messages.create({
      model: MODEL,
      max_tokens: 2048,
      messages: [{ role: "user", content: prompt }],
    });
  } catch (e: unknown) {
    const errText = e instanceof Error ? e.message : String(e);
    throw new Error(`Anthropic surface: ${errText}`);
  }

  const block = msg.content.find((b) => b.type === "text");
  if (!block || block.type !== "text") {
    throw new Error("Anthropic returned no text block");
  }

  let parsed: Record<string, unknown>;
  try {
    parsed = JSON.parse(extractJsonObject(block.text)) as Record<string, unknown>;
  } catch {
    throw new Error("Anthropic surface response was not valid JSON");
  }

  const absentRaw = parsed.absent_fields;
  const absent_fields: string[] = Array.isArray(absentRaw)
    ? absentRaw.filter((x): x is string => typeof x === "string")
    : ["absent_fields"];

  const whoRaw = parsed.who;
  const who: SurfaceResult["who"] = Array.isArray(whoRaw)
    ? whoRaw
        .map((row) => {
          if (!row || typeof row !== "object") return null;
          const r = row as Record<string, unknown>;
          const name = typeof r.name === "string" ? r.name : "";
          return {
            name,
            confidence_tier: asTier(r.confidence_tier, ConfidenceTier.SingleSource),
          };
        })
        .filter((x): x is NonNullable<typeof x> => x !== null && x.name.length > 0)
    : [];

  const whenRaw = parsed.when;
  let when: SurfaceResult["when"];
  if (whenRaw && typeof whenRaw === "object") {
    const w = whenRaw as Record<string, unknown>;
    when = {
      earliest_appearance: typeof w.earliest_appearance === "string" ? w.earliest_appearance : "",
      source: typeof w.source === "string" ? w.source : "",
      confidence_tier: asTier(w.confidence_tier, ConfidenceTier.SingleSource),
    };
  } else {
    when = {
      earliest_appearance: "",
      source: "",
      confidence_tier: ConfidenceTier.SingleSource,
    };
    if (!absent_fields.includes("when")) absent_fields.push("when");
  }

  const what = typeof parsed.what === "string" ? parsed.what : "";
  if (!what.trim() && !absent_fields.includes("what")) absent_fields.push("what");

  const modelUrlTier = sourceUrl
    ? asTier(parsed.source_url_confidence_tier, sourceUrlTier ?? ConfidenceTier.SingleSource)
    : null;

  const result: SurfaceResult = {
    what,
    what_confidence_tier: asTier(parsed.what_confidence_tier, ConfidenceTier.SingleSource),
    who,
    when,
    source_url: sourceUrl,
    source_url_confidence_tier: sourceUrl ? modelUrlTier : null,
    absent_fields: [...new Set(absent_fields)],
  };

  return result;
}
