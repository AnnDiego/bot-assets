# Punchy v1 — card renderer

Weekly virtual punchcards for chat: **one person, one goal/reward, one emoji**, **1–7 holes in a single horizontal row**.

Owner punches only; multi-punch/day OK; no unpunch; auto-renew; stop anytime; chat only; **no history in v1**.

## Product rules (locked)

| Rule | Detail |
|------|--------|
| Holes | 1–7, single horizontal row only (refuse multi-row) |
| Punch-up | Fill all holes to earn the prize |
| Punch-down | Allowance used; never exceed holes; refuse when full |
| Scene | Same scene all week; rotate across people / next week |
| Face | Person + goal + emoji must read on the card (fridge/partner glanceable) |
| Assets | Blank photoreal scenes + code overlays for exact punch counts |

## Layout

| Path | Role |
|------|------|
| `render_card.py` | Composite punches + labels onto a blank scene plate |
| `scenes/manifest.json` | Scene list + `card_roi` fractions (0–1) |
| `scenes/{wallet,hand,cafe,fridge}.jpg` | Blank photoreal plates |
| `cards.example.json` | Example card records (schema + sample rows) |

Working copy on the box often lives at `/workspace/punchy` (or a clone of this folder).

## Render

```bash
cd punchy   # or /workspace/punchy
python3 render_card.py \
  --scene-id wallet \
  --holes 5 --punched 2 \
  --emoji "📚" --person "Maya" \
  --goal "Ice cream after 5 reading nights" \
  --direction up \
  --out out/maya_2of5.png
```

Prints the output PNG path on stdout and exits 0.

## Scenes

Registered ids: `wallet`, `hand`, `cafe`, `fridge`. Measure `card_roi` as fractions of image width/height for the blank card face.

Do **not** commit synthetic/dev plates or `out/` renders to this public repo.
