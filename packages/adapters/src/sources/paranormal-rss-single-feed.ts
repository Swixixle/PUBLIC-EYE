import type { ActorEvent } from "@frame/types";
import type { ActorSourceCategory } from "@frame/types";
import { ConfidenceTier } from "@frame/types";
import {
  entityMentionedInRss,
  parseRss2Items,
  rssPubDateToIso,
} from "./rss-parse.js";

const UA = "FrameActorLayer/1.0 (https://github.com/Swixixle/FRAME)";
const SOURCE_CATEGORY: ActorSourceCategory = "paranormal_community";

/**
 * Fetch first working RSS URL, return up to `maxItems` entries mentioning `name`
 * (title or description). Community / paranormal — single-source tier.
 */
export async function lookupParanormalRssSingleFeed(
  name: string,
  feedUrls: readonly string[],
  sourceDisplayName: string,
  maxItems = 3,
): Promise<ActorEvent[]> {
  const q = name.trim();
  if (q.length < 2) return [];

  let xml = "";
  for (const url of feedUrls) {
    try {
      const r = await fetch(url, { headers: { "User-Agent": UA } });
      const text = await r.text();
      if (r.ok && text.includes("<rss") && text.includes("<item")) {
        xml = text;
        break;
      }
    } catch {
      /* try next */
    }
  }
  if (!xml) return [];

  const items = parseRss2Items(xml);
  const out: ActorEvent[] = [];
  for (const it of items) {
    if (!entityMentionedInRss(q, it.title, it.description)) continue;
    out.push({
      date: rssPubDateToIso(it.pubDate),
      type: "paranormal_rss_article",
      description: `${it.title} — ${sourceDisplayName} (community paranormal source; not an official record)`,
      source: it.link,
      confidence_tier: ConfidenceTier.SingleSource,
      source_category: SOURCE_CATEGORY,
    });
    if (out.length >= maxItems) break;
  }
  return out;
}
