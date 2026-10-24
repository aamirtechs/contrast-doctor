# Good first issues

Small, well-scoped tasks for new contributors. Each one can be done in a
single pull request. Comment on the issue before starting so two people do
not pick up the same one.

## 1. Support `oklch()` and `color-mix()` in CSS parsing

**What:** `parse_css` currently understands hex, `rgb()`/`rgba()`, and
named colors. Extend `_color_from_token` to also parse the modern
`oklch()` functional notation (convert to sRGB, clamping out-of-gamut
values) and simple `color-mix(in srgb, <color> <pct>, <color> <pct>)`
expressions. Skip anything that cannot be resolved to an opaque sRGB
color, and add tests with real-world design-token examples.

**Why:** Modern design systems increasingly ship tokens in OKLCH. A
contrast tool that silently skips them gives a false sense of coverage.

**Files:** `contrast_doctor.py` (`_color_from_token`), `tests/`.

## 2. Add a `--fail-below` summary threshold for CI

**What:** Today `--check` fails the build on any single failing pair. Add
a `--fail-below <pct>` flag: exit 1 only when the share of passing pairs
drops below the given percentage (for example `--fail-below 95`). Print
the pass percentage in the summary line either way.

**Why:** Large legacy palettes can have dozens of pre-existing failures.
Teams adopting the tool need a ratchet they can tighten over time instead
of an all-or-nothing gate.

**Files:** `contrast_doctor.py` (`main`, `render_text`), `README.md`,
`tests/`.

## 3. Report which WCAG criterion each pair maps to

**What:** Extend the text and JSON output so each pair notes the relevant
WCAG 2.1 success criterion: 1.4.3 Contrast (Minimum) for AA normal text,
1.4.6 Contrast (Enhanced) for AAA, and a note that large text maps to the
same criteria with relaxed thresholds. Keep it factual: criterion number,
name, and the threshold used.

**Why:** Accessibility audit reports cite criteria, not just ratios. This
makes contrast-doctor output paste-ready for audit documentation.

**Files:** `contrast_doctor.py` (`render_text`, `report_to_json`),
`README.md`, `tests/`.

## 4. Add a `--sort worst` option for large palettes

**What:** Add a `--sort` flag with values `worst` (default today: file
order) and `file`. With `worst`, failing pairs print first ordered by
ascending ratio, so the most severe violations are visible without
scrolling. Apply the same ordering to the JSON `pairs` array.

**Why:** On a 50-color palette the all-pairs mode produces 1,225 lines.
The worst violations should never be buried at the bottom.

**Files:** `contrast_doctor.py` (`main`, `render_text`, `report_to_json`),
`README.md`, `tests/`.
