import { lookupParanormalRssSingleFeed } from "./paranormal-rss-single-feed.js";

const FEED_URLS = [
  "https://subscribe.forteantimes.com/feed/",
  "https://www.forteantimes.com/feed",
] as const;

export async function lookupForteanTimes(name: string) {
  return lookupParanormalRssSingleFeed(name, FEED_URLS, "Fortean Times");
}
