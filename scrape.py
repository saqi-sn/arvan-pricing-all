#!/usr/bin/env python3
"""
Scrape every price table from https://www.arvancloud.ir/fa/pricing/all into JSON.

The page is server-rendered and uses Alpine.js (`x-show="region === 'europe'"`)
to hide the Europe variants behind a toggle, so both regions are present in the
static HTML and no browser is needed.

Usage:
    python scrape.py                  # fetch live page -> arvan-pricing-all.json
    python scrape.py --html page.html # parse a saved copy
    python scrape.py -o out.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
from datetime import datetime, timezone

from bs4 import BeautifulSoup

SOURCE_URL = "https://www.arvancloud.ir/fa/pricing/all"
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36"
)

# Persian product headings -> stable English slugs.
SLUGS = {
    "شبکه توزیع محتوا (CDN)": "cdn",
    "سرور ابری": "cloud-server",
    "فضای ابری": "object-storage",
    "پلتفرم ویدیو": "video-platform",
    "دیتابیس ابری": "cloud-database",
    "پردازش لبه": "edge-computing",
    "آروان‌درایو": "arvan-drive",
    "لاگ ابری": "cloud-log",
    "کانتینر ابری": "cloud-container",
    "سرویس هوش مصنوعی": "ai-service",
    "خدمات پشتیبانی": "support-services",
}

EN_NAMES = {
    "cdn": "Content Delivery Network (CDN)",
    "cloud-server": "Cloud Server",
    "object-storage": "Object Storage",
    "video-platform": "Video Platform",
    "cloud-database": "Cloud Database",
    "edge-computing": "Edge Computing",
    "arvan-drive": "ArvanDrive",
    "cloud-log": "Cloud Log",
    "cloud-container": "Cloud Container",
    "ai-service": "AI Service",
    "support-services": "Support Services",
}

FA_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")
# Arabic comma / Persian thousands separator / ASCII comma.
SEPARATORS = dict.fromkeys(map(ord, ",٬،"), None)

REGION_RE = re.compile(r"===\s*'(\w+)'")


def norm(text: str | None) -> str:
    """Collapse whitespace, keeping ZWNJ (U+200C) which is meaningful in Persian."""
    return re.sub(r"[^\S‌]+", " ", text or "").strip()


def parse_price(cell: str) -> dict:
    """Turn a price cell into {raw, is_free, amount, currency, note}."""
    raw = norm(cell)
    if not raw or raw in {"-", "—"}:
        return {"raw": raw or None, "is_free": False, "amount": None,
                "currency": None, "note": None}

    is_free = "رایگان" in raw
    has_toman = "تومان" in raw

    digits = raw.translate(FA_DIGITS).translate(SEPARATORS)
    match = re.search(r"\d+(?:\.\d+)?", digits)

    # Anything left over after stripping the number, the currency and "free"
    # is a qualifier, e.g. "به‌ازای هر ابرک" (per instance).
    leftover = norm(
        re.sub(r"[0-9]+(?:\.[0-9]+)?", "", raw.translate(FA_DIGITS).translate(SEPARATORS))
        .replace("رایگان", "")
        .replace("تومان", "")
    )
    note = leftover or None

    if is_free:
        return {"raw": raw, "is_free": True, "amount": 0,
                "currency": None, "note": note}
    if match:
        value = float(match.group())
        return {"raw": raw, "is_free": False,
                "amount": int(value) if value.is_integer() else value,
                "currency": "IRT" if has_toman else None, "note": note}
    return {"raw": raw, "is_free": False, "amount": None,
            "currency": None, "note": None}


def region_of(card, section) -> str | None:
    """Walk up from a card to the nearest Alpine x-show and read its region."""
    node = card
    while node is not None and node is not section:
        x_show = node.get("x-show") if hasattr(node, "get") else None
        if x_show:
            match = REGION_RE.search(x_show)
            if match:
                return match.group(1)
        node = node.parent
    return None


def is_card(tag) -> bool:
    classes = tag.get("class") or []
    return tag.name == "div" and "bg-white" in classes and "rounded-lg" in classes


def element_children(tag):
    return [c for c in tag.children if getattr(c, "name", None)]


def parse_table(card, section) -> dict | None:
    """A card is a header row followed by data rows; all rows are flex divs."""
    rows = [r for r in element_children(card) if element_children(r)]
    if not rows:
        return None

    columns = [norm(c.get_text()) for c in element_children(rows[0])]
    if not columns:
        return None

    # The middle columns are positional: locate them by their header text.
    tier_idx = next((i for i, h in enumerate(columns) if i > 0 and "پلکان" in h), None)
    unit_idx = next((i for i, h in enumerate(columns) if i > 0 and h == "واحد"), None)
    price_idx = len(columns) - 1

    out_rows = []
    last_item = None
    for row in rows[1:]:
        cells = [norm(c.get_text()) for c in element_children(row)]
        if not cells:
            continue

        # An empty first cell means the row continues the previous item's
        # tier list (the page's visual equivalent of a rowspan).
        continues = not cells[0]
        item = cells[0] or last_item
        if cells[0]:
            last_item = cells[0]

        entry: dict = {"item": item or None}
        if continues:
            entry["continues_previous_item"] = True
        if unit_idx is not None and unit_idx < len(cells):
            entry["unit"] = cells[unit_idx] or None
        if tier_idx is not None and tier_idx < len(cells):
            tier = cells[tier_idx]
            entry["tier"] = tier if tier and tier != "-" else None
        entry["price"] = parse_price(cells[price_idx] if price_idx < len(cells) else "")
        entry["raw_cells"] = cells
        out_rows.append(entry)

    return {
        "name": columns[0] or None,
        "region": region_of(card, section),
        "price_basis": columns[price_idx] or None,
        "columns": columns,
        "rows": out_rows,
    }


def collect_notes(section, cards, title: str) -> list[str]:
    """Footnotes and prose that sit in the section but outside any price card."""
    notes = []
    for tag in section.find_all(["p", "span", "div", "li"]):
        if any(card in tag.parents for card in cards) or tag in cards:
            continue
        # Leaf nodes only, so container divs don't swallow whole sections.
        # Paragraphs are kept even when they wrap an inline link.
        if tag.name != "p" and element_children(tag):
            continue
        text = norm(tag.get_text())
        if len(text) > 20 and text != title and text not in notes:
            notes.append(text)
    return notes


def scrape(html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    sections = soup.find_all(id=re.compile(r"^pricing-package-\d+$"))
    if not sections:
        raise SystemExit("No pricing sections found - page layout may have changed.")

    products = []
    for section in sections:
        heading = section.find(["h1", "h2", "h3", "h4"])
        title = norm(heading.get_text()) if heading else norm(
            section.get_text().strip().split("\n")[0]
        )
        slug = SLUGS.get(title)

        cards = [t for t in section.find_all("div") if is_card(t)]

        # Every section carries an (often empty) Europe panel; only the ones
        # with content actually offer a region switcher.
        europe_panels = [
            t for t in section.find_all(attrs={"x-show": True})
            if "europe" in (t.get("x-show") or "")
        ]
        has_europe = any(norm(p.get_text()) for p in europe_panels)

        tables = []
        for card in cards:
            table = parse_table(card, section)
            if table:
                if not has_europe:
                    table["region"] = None
                tables.append(table)

        products.append({
            "id": section.get("id"),
            "slug": slug,
            "name_fa": title,
            "name_en": EN_NAMES.get(slug or ""),
            "has_region_switcher": has_europe,
            "tables": tables,
            "notes": collect_notes(section, cards, title),
        })

    version_links = []
    seen = set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "/fa/pricing/all" not in href:
            continue
        url = href if href.startswith("http") else "https://www.arvancloud.ir" + href
        if url in seen:
            continue
        label = norm(a.get_text())
        if not label:
            continue
        seen.add(url)
        version_links.append({
            "label_fa": label,
            "url": url,
            "is_current": "version=" not in url,
        })

    return {
        "source": {
            "url": SOURCE_URL,
            "page_title": norm(soup.title.get_text() if soup.title else ""),
            "scraped_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        },
        "currency": {
            "code": "IRT",
            "name_fa": "تومان",
            "note": "Amounts are in Iranian Toman. `amount` is null when the cell "
                    "holds no number; `is_free` marks cells reading «رایگان».",
        },
        "regions": {
            "values": ["iran", "europe"],
            "note_fa": "تنها «سرور ابری» قیمت متفاوتی برای اروپا دارد؛ "
                       "برای سایر محصولات مقدار region برابر null است.",
            "note_en": "Only Cloud Server has separate Europe pricing (behind a "
                       "toggle on the page). Elsewhere `region` is null, meaning "
                       "the price is not region-specific.",
        },
        "price_versions": version_links,
        "products": products,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--html", help="parse a local HTML file instead of fetching")
    parser.add_argument("-o", "--output", default="arvan-pricing-all.json")
    args = parser.parse_args()

    if args.html:
        with open(args.html, encoding="utf-8") as fh:
            html = fh.read()
    else:
        request = urllib.request.Request(SOURCE_URL, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(request, timeout=60) as response:
            html = response.read().decode("utf-8", "replace")

    data = scrape(html)
    with open(args.output, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
        fh.write("\n")

    tables = sum(len(p["tables"]) for p in data["products"])
    rows = sum(len(t["rows"]) for p in data["products"] for t in p["tables"])
    print(
        f"{args.output}: {len(data['products'])} products, "
        f"{tables} tables, {rows} rows",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
