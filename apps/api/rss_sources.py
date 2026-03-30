"""
Curated RSS feed registry across global media ecosystems.
All feeds are public and require no API key.
"""

from __future__ import annotations

RSS_FEEDS = [
    # Western / Anglophone
    {
        "id": "ap_top",
        "outlet": "AP News",
        "ecosystem": "western_anglophone",
        "url": "https://feeds.apnews.com/rss/apf-topnews",
    },
    {
        "id": "ap_world",
        "outlet": "AP News",
        "ecosystem": "western_anglophone",
        "url": "https://feeds.apnews.com/rss/apf-worldnews",
    },
    {
        "id": "reuters_world",
        "outlet": "Reuters",
        "ecosystem": "western_anglophone",
        "url": "https://feeds.reuters.com/reuters/worldNews",
    },
    {
        "id": "bbc_world",
        "outlet": "BBC",
        "ecosystem": "western_anglophone",
        "url": "http://feeds.bbci.co.uk/news/world/rss.xml",
    },
    {
        "id": "guardian_world",
        "outlet": "The Guardian",
        "ecosystem": "western_anglophone",
        "url": "https://www.theguardian.com/world/rss",
    },
    {
        "id": "nyt_world",
        "outlet": "New York Times",
        "ecosystem": "western_anglophone",
        "url": "https://rss.nytimes.com/services/xml/rss/nyt/World.xml",
    },
    # Al Jazeera
    {
        "id": "aljazeera_world",
        "outlet": "Al Jazeera",
        "ecosystem": "arab_gulf",
        "url": "https://www.aljazeera.com/xml/rss/all.xml",
    },
    {
        "id": "aljazeera_mideast",
        "outlet": "Al Jazeera",
        "ecosystem": "arab_gulf",
        "url": "https://www.aljazeera.com/xml/rss/all.xml",
    },
    # RT (Russian state)
    {"id": "rt_news", "outlet": "RT", "ecosystem": "russian_state", "url": "https://www.rt.com/rss/news/"},
    # Chinese state
    {
        "id": "xinhua_world",
        "outlet": "Xinhua",
        "ecosystem": "chinese_state",
        "url": "http://www.xinhuanet.com/english/rss/worldrss.xml",
    },
    {
        "id": "globaltimes",
        "outlet": "Global Times",
        "ecosystem": "chinese_state",
        "url": "https://www.globaltimes.cn/rss/outbrain.xml",
    },
    # Israeli
    {
        "id": "haaretz",
        "outlet": "Haaretz",
        "ecosystem": "israeli",
        "url": "https://www.haaretz.com/cmlink/1.4",
    },
    {
        "id": "timesofisrael",
        "outlet": "Times of Israel",
        "ecosystem": "israeli",
        "url": "https://www.timesofisrael.com/feed/",
    },
    # South Asian
    {"id": "dawn", "outlet": "Dawn", "ecosystem": "south_asian", "url": "https://www.dawn.com/feeds/home"},
    {
        "id": "thehindu",
        "outlet": "The Hindu",
        "ecosystem": "south_asian",
        "url": "https://www.thehindu.com/news/international/?service=rss",
    },
    # European
    {
        "id": "dw_world",
        "outlet": "DW",
        "ecosystem": "european",
        "url": "https://rss.dw.com/rdf/rss-en-world",
    },
    {
        "id": "euronews",
        "outlet": "Euronews",
        "ecosystem": "european",
        "url": "https://feeds.feedburner.com/euronews/en/news/",
    },
]


def get_feeds_for_ecosystems(ecosystem_ids: list[str] | None = None) -> list[dict]:
    if not ecosystem_ids:
        return RSS_FEEDS
    return [f for f in RSS_FEEDS if f["ecosystem"] in ecosystem_ids]
