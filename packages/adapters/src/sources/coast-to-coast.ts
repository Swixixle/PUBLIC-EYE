import { lookupParanormalRssSingleFeed } from "./paranormal-rss-single-feed.js";

const FEED_URLS = [
  "https://rss.premiereradio.net/podcast/coast.xml",
  "http://www.coasttocoastam.com/rss/complete/30",
  "https://www.coasttocoastam.com/feed/",
] as const;

export async function lookupCoastToCoast(name: string) {
  return lookupParanormalRssSingleFeed(name, FEED_URLS, "Coast to Coast AM");
}
