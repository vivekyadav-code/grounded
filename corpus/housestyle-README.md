# housestyle

**An illustration set that draws the icon you don't have — in a style you lock once.**

Give it a house style as one JSON file. Ask it for any object. It returns a
clean, editable SVG that matches everything else in the set, and freezes that
drawing forever so it never drifts.

```bash
./hs forge northwind shield rocket inbox
./hs sheet northwind --open        # the page you send a customer
```

## Why this isn't an image generator

Diffusion models give *approximate* style consistency and hand you a PNG.
This gives:

- **exact** consistency — a drawing is validated, then frozen; ask twice, get
  the same bytes
- **editable vectors** — one shape per line, no transforms to unpick; every
  element is a real object in Figma or Illustrator
- **any size** — resolution-independent, and under 1KB a file
- **mechanical enforcement** — off-palette or out-of-bounds work never reaches
  disk, so the 200th drawing matches the 1st
- **a legibility check** — a drawing that doesn't read as the thing it is
  named is rejected too

The model writes JSON shape *data*, never code. Nothing it returns is executed.

## How a style works

`styles/<name>.json` drives two things at once, which is the whole trick: the
**prompt** the model is given, and the **validator** that rejects the result.
Because both come from one file, a drawing can't be "mostly" on style.

```json
{
  "palette":      { "ink": "#1e293b", "white": "#ffffff", "indigo": "#4f46e5" },
  "background":   "white",
  "shapes":       [3, 8],
  "max_coord":    150,
  "stroke_width": [6, 9],
  "style_notes":  "friendly geometric spot illustration. Thin even outlines...",
  "draw_rules":   ["Exactly one element may use #4f46e5 — that is the focal point."],
  "examples":     [{ "name": "phone", "rows": [["rect", { "...": "..." }]] }]
}
```

Rejections are fed back to the model as the retry prompt, so it converges
instead of guessing.

| Key | Enforced how |
|---|---|
| `palette` | every `fill`/`stroke` must be one of these, or `none` |
| `shapes` | shape count range |
| `max_coord` | coordinates must stay inside the drawing box |
| `stroke_width` | numeric range |
| `allowed_tags` | may narrow the renderable set, never widen it |
| `accent_area` | share of filled area the accent may cover — a band, so a *missing* focal point fails too |
| `neutrals` | which palette entries count as body/outline rather than accent |
| `style_notes`, `draw_rules`, `examples` | prompt only — taste, not geometry |

Extents are **measured** from the shapes, never taken from the model: it is
unreliable about how big it drew something, the geometry is not. `accent_area`
is measured the same way — it exists because geometry checks alone cannot tell
"one indigo accent" from "the object is indigo", and both passed everything
else. It is opt-in: a style is allowed to say a fully coloured object is
correct, which `beyond-obvious` does.

## Encoding a real customer, in about ten minutes

1. `cp styles/_TEMPLATE.json styles/<prospect>.json`
2. Pull their **palette** off their site — brand page, or an SVG from their
   marketing pages. Name the roles the way they think about them.
3. Open one of their existing illustrations and read off **stroke width**,
   whether corners are rounded, and whether fills are flat. These three
   decide most of the resemblance.
4. Write `style_notes` as if briefing a freelancer.
5. Forge three throwaway objects. Every miss you see becomes a line in
   `draw_rules` — that is the loop, and it converges fast.
6. Paste one drawing you are happy with into `examples`. It anchors the rest.

If they publish an SVG you can legitimately use, its shape rows can go
straight into `examples` — that is the single strongest anchor available.

## The recognition gate

The palette, geometry and accent rules all read the shape *data*. None of them
can see that a "meditation cushion" came out looking like a chef's hat — it was
on-palette, in-bounds and inside the accent band, and wrong.

So `--recognize` looks at pixels: render the drawing with Chrome, show it to a
vision model that has **not** been told what it is meant to be, and ask what it
sees. The `<title>`, `id` and `aria-label` are stripped first — a model that can
read the answer is not being tested on the picture. If the guesses don't share a
word with the name, that becomes the retry instruction:

```
! running_shoe attempt 1 rejected: the drawing does not read as 'running_shoe' —
  shown it without being told, a viewer called it: hot dog, sausage bun, frankfurter.
! running_shoe attempt 2 rejected: ... a viewer called it: beret, hat, cap.
+ running_shoe  read as: shoe, slipper, sneaker
```

Matching is deliberately generous — `key_pair` guessed as "key" is a hit, and
`teacup` guessed as "cup of tea" is a hit — because the gate exists to catch a
shoe that reads as a headlamp, not to police wording.

It needs Chrome (any Chromium build; `HOUSESTYLE_CHROME` overrides the path) and
`GEMINI_API_KEY`. **A gate that cannot run never counts as a gate that passed**:
on a rate limit or a missing rasteriser it says so, draws without the check, and
lists exactly which drawings went unchecked.

Free-tier vision quota is small, so `verify` sleeps between calls (`--delay`).

## Commands

| | |
|---|---|
| `./hs styles` | list styles and library sizes |
| `./hs forge <style> <name>...` | draw and freeze (`--force` to redraw) |
| `./hs export <style>` | write every drawing as `.svg` |
| `./hs sheet <style> [--open]` | contact sheet page |
| `./hs serve [--port 8787]` | run the local site — the page people click |
| `./hs verify <style> [name...]` | check the library still *reads* as what it is named |
| `./hs show <style> <name>` | print one SVG |

## The local site

```bash
./hs serve
```

Opens `http://127.0.0.1:8787`. Stdlib `http.server` — no framework, no build
step, nothing to install.

The demo on it is not a mock-up. `POST /api/forge` runs the real forge with the
real gates and returns every rejection along the way, so a visitor watches a
drawing get refused and redrawn rather than reading a claim that it would be.
Asking for something already in the library returns the frozen file instantly,
which demonstrates the consistency guarantee better than any copy on the page.

Bound to loopback on purpose: the page can spend LLM calls, so it must not be
reachable from the network without a deliberate tunnel.

| route | |
|---|---|
| `GET /` | the page |
| `GET /api/styles` | every style with its palette and drawings |
| `GET /api/health` | liveness |
| `POST /api/forge` | `{style, name, recognize?}` &rarr; rows + the gate log |

## Layout

```
housestyle/      style.py  validate.py  forge.py  render.py  recognize.py
                 web.py  cli.py
                 llm_providers.py   (claude -> gemini -> groq -> local mlx)
web/index.html   the local site's single page
styles/          one JSON per house style
library/<style>/ frozen drawings — the asset; commit this
out/             generated SVGs and contact sheets
tests/           19 offline tests
```

Requires Python 3 and nothing else — no pip install. Needs one working LLM
provider: the `claude` CLI, or a `GEMINI_API_KEY` / `GROQ_API_KEY` in `env.sh`.

```bash
python3 -m unittest discover -s tests
```

## Included styles

Four portfolio styles, built on deliberately different **construction
methods** — the point is that the spec holds up across real stylistic range,
not just recolouring:

- **northwind** — B2B SaaS: white bodies, thin slate outlines, one indigo accent.
- **atlas** — fintech: duotone silhouettes with *no outlines at all*.
- **sprig** — wellness: thick organic outlines, warm palette, deliberately soft.
- **terminal** — devtools: monoline schematic with *no fills at all*, on dark.
Plus **beyond-obvious** — ported verbatim from the video studio's `prop_forge.py`,
  with its 75 existing drawings imported. It is the regression case: all 75
  still validate under the generalized spec, so if that stops being true, the
  generalization broke.

## Provenance

The forge, validator and measured-extent approach come from `prop_forge.py` in
the ai-video-generator project, where they kept props on-model across 157
videos. This project makes the style itself the input.
