# arvan-pricing-all

Machine-readable snapshot of every price table on ArvanCloud's
["all products" pricing page](https://www.arvancloud.ir/fa/pricing/all),
including the **Europe** cloud-server prices that the page keeps behind a
region toggle.

- [`arvan-pricing-all.json`](arvan-pricing-all.json) — the data
- [`scrape.py`](scrape.py) — the scraper that produces it

**11 products · 52 tables · 242 price rows.** Amounts are Iranian Toman (`IRT`).

> Unofficial snapshot, not affiliated with ArvanCloud. Prices change — re-run
> the scraper rather than trusting the committed timestamp.

## Regenerating

```bash
pip install beautifulsoup4
python scrape.py                     # fetch live -> arvan-pricing-all.json
python scrape.py --html page.html    # parse a saved copy
python scrape.py -o custom.json
```

The page is server-rendered and uses Alpine.js (`x-show="region === 'europe'"`)
to hide the Europe tables, so **both regions ship in the static HTML** and no
browser or JS execution is needed.

## Structure

```jsonc
{
  "source":   { "url": "...", "page_title": "...", "scraped_at": "ISO-8601" },
  "currency": { "code": "IRT", "name_fa": "تومان", "note": "..." },
  "regions":  { "values": ["iran", "europe"], "note_fa": "...", "note_en": "..." },
  "price_versions": [            // the page's price-archive selector
    { "label_fa": "...", "url": "...", "is_current": true }
  ],
  "products": [
    {
      "id": "pricing-package-1",
      "slug": "cloud-server",
      "name_fa": "سرور ابری",
      "name_en": "Cloud Server",
      "has_region_switcher": true,
      "notes": ["footnotes that sit outside the price tables"],
      "tables": [
        {
          "name": "پردازنده",
          "region": "europe",      // "iran" | "europe" | null
          "price_basis": "هر vCPU", // header of the price column
          "columns": ["پردازنده", "هر vCPU"],
          "rows": [
            {
              "item": "Basic",
              "unit": null,         // present when the table has a «واحد» column
              "tier": null,         // present when it has a «پلکان استفاده» column
              "price": {
                "raw": "۲۸۰,۰۰۰ تومان",
                "is_free": false,
                "amount": 280000,
                "currency": "IRT",
                "note": null        // qualifier, e.g. "به‌ازای هر ابرک"
              },
              "price_reduced": false, // page shows a «کاهش‌یافته» badge
              "raw_cells": ["Basic", "۲۸۰,۰۰۰ تومان"]
            }
          ]
        }
      ]
    }
  ]
}
```

### Field notes

- **`region`** is `"iran"` or `"europe"` only for Cloud Server, the one product
  with a real region toggle. Everywhere else it is `null`, meaning the price is
  not region-specific. `has_region_switcher` tells you which case you are in.
- **`price.amount`** is the number with Persian digits and thousands separators
  normalized; `0` together with `is_free: true` for «رایگان»; `null` when the
  cell holds no number (e.g. `-`).
- **`price.note`** captures text left over next to the number — usually a scope
  qualifier like «به‌ازای هر حساب کاربری» (per account) or «به‌ازای هر ابرک»
  (per instance) that is easy to miss when reading the page.
- **`tier`** is the usage step («تا ۲۵۰ گیگابایت», «بیش از ۱۰۰ ترابایت»).
  The page renders a tier list as one labelled row plus unlabelled rows; the
  scraper forward-fills `item` and marks those rows
  `"continues_previous_item": true`.
- **`price_reduced`** is `true` for the 18 rows the page marks with a
  «کاهش‌یافته» (price-reduced) tooltip badge. That badge is rendered as an
  extra element *outside* the normal cells, so a naive scrape shifts the whole
  row by one column and reads the tier name as the price — the scraper takes
  `div` cells only to stay aligned.
- **`raw_cells`** keeps every cell verbatim, so nothing is lost if the
  normalized fields don't fit your use case.
- **`columns`** varies per table (2–4 columns); read `price_basis` for the unit
  the price applies to.

## Products covered

| slug | Persian | region prices |
|---|---|---|
| `cdn` | شبکه توزیع محتوا (CDN) | — |
| `cloud-server` | سرور ابری | Iran + Europe |
| `object-storage` | فضای ابری | — |
| `video-platform` | پلتفرم ویدیو | — |
| `cloud-database` | دیتابیس ابری | — |
| `edge-computing` | پردازش لبه | — |
| `arvan-drive` | آروان‌درایو | — |
| `cloud-log` | لاگ ابری | — |
| `cloud-container` | کانتینر ابری | — |
| `ai-service` | سرویس هوش مصنوعی | — (per-token pricing lives in the user panel) |
| `support-services` | خدمات پشتیبانی | — |

Within Cloud Server, the GPU and dedicated-server tables sit outside the
toggle and carry `region: null`. Europe differs from Iran on vCPU, RAM,
block/file storage, IPv4 — and on traffic, where Europe bills send+receive
together with a different free allowance.

## Example

```python
import json

data = json.load(open("arvan-pricing-all.json"))
server = next(p for p in data["products"] if p["slug"] == "cloud-server")

for table in server["tables"]:
    if table["name"] == "پردازنده":
        print(table["region"], table["price_basis"])
        for row in table["rows"]:
            print("  ", row["item"], row["price"]["amount"])
```
