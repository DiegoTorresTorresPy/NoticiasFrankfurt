from __future__ import annotations

import pathlib
import sys

ROOT_DIR = pathlib.Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from generate_site import CATEGORY_CONFIGS, parse_google_news_feed


def main() -> int:
    commute_category = next((item for item in CATEGORY_CONFIGS if item["key"] == "commute"), None)
    alerts_category = next((item for item in CATEGORY_CONFIGS if item["key"] == "alerts"), None)
    categories = [category for category in [commute_category, alerts_category] if category is not None]

    for category in categories:
        print(f"\n=== {category['label']} ===")
        for item in parse_google_news_feed(category):
            source = "ENLACE_GOOGLE" if "news.google" in item.link else "ENLACE_REAL"
            print(f"- {item.title}")
            print(f"  link: {item.link}")
            print(f"  origen: {source}")
            if item.initialization_hint:
                print(f"  inicializacion: {item.initialization_hint}")
            print(f"  resumen: {item.description[:120]}...")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
