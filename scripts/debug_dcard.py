import json
import sys
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.crawler.config import CrawlConfig
from backend.crawler.dcard import DcardBrowserSession, DcardCrawler
from backend.crawler.normalizer import is_relevant

config = CrawlConfig(aftersales_only=False)
crawler = DcardCrawler(config)
url = f"https://www.dcard.tw/service/api/v2/search/posts?query={quote('lexus')}&limit=10"

result = {}
with DcardBrowserSession(config) as session:
    raw = session.fetch_json(url)
    refs = crawler._parse_list(raw)
    result["parsed"] = len(refs)
    result["relevance"] = []
    for ref in refs[:5]:
        ok = is_relevant(
            ref.title,
            config.relevance_keywords,
            config.service_keywords,
            aftersales_only=False,
        )
        result["relevance"].append({"title": ref.title, "ok": ok})

Path("data/dcard_debug.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
