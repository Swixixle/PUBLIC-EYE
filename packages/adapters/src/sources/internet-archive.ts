import type { ActorEvent } from "@frame/types";
import { ConfidenceTier } from "@frame/types";

const UA = "FrameActorLayer/1.0 (https://github.com/Swixixle/FRAME)";

function tierForYear(year: number): ConfidenceTier {
  if (!Number.isFinite(year)) return ConfidenceTier.SingleSource;
  if (year < 1900) return ConfidenceTier.OfficialPrimary;
  if (year <= 1950) return ConfidenceTier.CrossCorroborated;
  return ConfidenceTier.SingleSource;
}

function oneLineDescription(raw: unknown): string {
  if (raw == null) return "";
  const s = Array.isArray(raw) ? String(raw[0] ?? "") : String(raw);
  const t = s.replace(/\s+/g, " ").trim();
  if (!t) return "";
  const cut = t.indexOf(". ");
  return (cut > 0 ? t.slice(0, cut + 1) : t).slice(0, 400);
}

/**
 * Top Internet Archive text items matching `name` (mediatype:texts in query, not URL param).
 */
export async function lookupInternetArchive(name: string): Promise<ActorEvent[]> {
  const q = name.trim();
  if (q.length < 2) return [];
  const safe = q.replace(/"/g, "");
  const query = `mediatype:texts AND (title:(${safe}) OR description:(${safe}))`;
  const url =
    `https://archive.org/advancedsearch.php?q=${encodeURIComponent(query)}` +
    `&fl=identifier,title,year,description&output=json&rows=3&sort%5B%5D=year+desc`;
  try {
    const r = await fetch(url, { headers: { "User-Agent": UA } });
    if (!r.ok) return [];
    const data = (await r.json()) as {
      response?: { docs?: Array<{ identifier?: string; title?: string; year?: string | number; description?: string | string[] }> };
    };
    const docs = data.response?.docs ?? [];
    const out: ActorEvent[] = [];
    for (const d of docs.slice(0, 3)) {
      const id = d.identifier?.trim();
      if (!id) continue;
      const title = (d.title ?? "").trim() || id;
      const yearNum =
        typeof d.year === "number"
          ? d.year
          : parseInt(String(d.year ?? ""), 10);
      const dateStr = Number.isFinite(yearNum) ? `${yearNum}-01-01` : "unknown";
      const desc = oneLineDescription(d.description) || title;
      out.push({
        date: dateStr,
        type: "internet_archive_text",
        description: desc,
        source: `https://archive.org/details/${encodeURIComponent(id)}`,
        confidence_tier: tierForYear(yearNum),
      });
    }
    return out;
  } catch {
    return [];
  }
}
