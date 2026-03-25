import { lookupParanormalRssSingleFeed } from "./paranormal-rss-single-feed.js";

/** Squarespace exposes RSS via `?format=rss` (plain `/feed` 404s). */
const FEED_URLS = [
  "https://www.singularfortean.com/home?format=rss",
  "https://singularfortean.com/home?format=rss",
] as const;

export async function lookupSingularFortean(name: string) {
  return lookupParanormalRssSingleFeed(name, FEED_URLS, "Singular Fortean Society");
}
