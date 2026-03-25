import { lookupParanormalRssSingleFeed } from "./paranormal-rss-single-feed.js";

const FEED_URLS = ["https://cryptomundo.com/feed/", "https://www.cryptomundo.com/feed/"] as const;

export async function lookupCryptomundo(name: string) {
  return lookupParanormalRssSingleFeed(name, FEED_URLS, "Cryptomundo");
}
