import type { ActorEvent } from "@frame/types";
import { ConfidenceTier } from "@frame/types";

const UA = "FrameActorLayer/1.0 (https://github.com/Swixixle/FRAME)";

type LocResult = {
  title?: string;
  date?: string;
  url?: string;
  id?: string;
};

function parseNewspaperTitle(title: string): string {
  const t = title.replace(/\s+/g, " ").trim();
  const m = t.match(/Image\s+\d+\s+of\s+(.+?),\s*(\d{4}-\d{2}-\d{2})\s*$/i);
  if (m) return `${m[1].trim()} — ${m[2]}`;
  return t.slice(0, 240);
}

/**
 * Historic newspaper hits (Chronicling America corpus via loc.gov newspapers JSON).
 * Tries legacy `chroniclingamerica.loc.gov` JSON shape when available; falls back to `loc.gov/newspapers`.
 */
export async function lookupChroniclingAmerica(name: string): Promise<ActorEvent[]> {
  const q = name.trim();
  if (q.length < 2) return [];

  const legacyUrl =
    `https://chroniclingamerica.loc.gov/search/pages/results/?format=json&proxtext=${encodeURIComponent(q)}` +
    `&dateFilterType=yearRange&date1=1770&date2=1963&rows=3`;

  try {
    const legacyR = await fetch(legacyUrl, { headers: { "User-Agent": UA } });
    const legacyText = await legacyR.text();
    if (legacyR.ok && legacyText.trimStart().startsWith("{")) {
      const j = JSON.parse(legacyText) as {
        items?: Array<{ title?: string; date?: string; url?: string }>;
      };
      const items = j.items ?? [];
      if (items.length > 0) {
        return items.slice(0, 3).map((it) => ({
          date: (it.date ?? "unknown").trim() || "unknown",
          type: "chronicling_america_page",
          description: `${(it.title ?? "").trim() || "Newspaper page"}`,
          source: (it.url ?? "").trim() || legacyUrl,
          confidence_tier: ConfidenceTier.CrossCorroborated,
        }));
      }
    }
  } catch {
    /* fall through */
  }

  const fallbackUrl = `https://www.loc.gov/newspapers/?q=${encodeURIComponent(q)}&fo=json&rows=3`;
  try {
    const r = await fetch(fallbackUrl, { headers: { "User-Agent": UA } });
    if (!r.ok) return [];
    const data = (await r.json()) as { results?: LocResult[]; content?: { results?: LocResult[] } };
    const rows = data.results ?? data.content?.results ?? [];
    const out: ActorEvent[] = [];
    for (const row of rows.slice(0, 3)) {
      const date = (row.date ?? "unknown").trim() || "unknown";
      const title = parseNewspaperTitle(row.title ?? row.id ?? "Newspaper item");
      const pageUrl = (row.url ?? "").trim() || fallbackUrl;
      out.push({
        date,
        type: "chronicling_america_page",
        description: title,
        source: pageUrl,
        confidence_tier: ConfidenceTier.CrossCorroborated,
      });
    }
    return out;
  } catch {
    return [];
  }
}
