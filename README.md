# contrast-doctor

[![GitHub stars](https://img.shields.io/github/stars/aamirtechs/contrast-doctor?style=social)](https://github.com/aamirtechs/contrast-doctor/stargazers) [![GitHub forks](https://img.shields.io/github/forks/aamirtechs/contrast-doctor?style=social)](https://github.com/aamirtechs/contrast-doctor/network/members) [![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://github.com/aamirtechs/contrast-doctor/blob/main/LICENSE) [![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](https://github.com/aamirtechs/contrast-doctor/issues)

A bulk WCAG contrast checker for color palettes and CSS files that not only
reports failing pairs but suggests concrete fixed colors. Catch contrast
bugs before design reviews.

contrast-doctor is a zero-dependency Python CLI. It reads colors from CSS
files (custom properties plus `color`/`background` declarations), plain
palette files (one hex per line), and JSON palettes (`{"name": "#hex"}`),
checks every foreground/background pair against WCAG 2.1 contrast ratios,
and for each failure suggests the nearest adjusted color (minimal lightness
shift in HSL space, hue preserved) that passes your target level.

## Install

Requires Python 3.9 or newer. No dependencies beyond the standard library.

```bash
pip install contrast-doctor
```

Or run it straight from the source checkout:

```bash
python3 contrast_doctor.py examples/theme.css --bg "#ffffff"
```

## Usage

Check a stylesheet's custom properties against a white background, failing
the build on any AA violation (CI gate):

```bash
python3 contrast_doctor.py examples/theme.css --bg "#ffffff" --check
```

Captured output (exit code 1, because pairs fail):

```
contrast-doctor 1.0.0 | AA normal text, threshold 4.50:1
input: examples/theme.css (9 pairs)

PASS  --brand-600 (#2563eb) on background (#ffffff)  5.17:1
PASS  --brand-700 (#1d4ed8) on background (#ffffff)  6.70:1
PASS  --ink (#111827) on background (#ffffff)  17.74:1
FAIL  --text-muted (#9ca3af) on background (#ffffff)  2.54:1 < 4.50:1
      fix: --text-muted: #6e7788;  /* 4.51:1 vs #ffffff */
FAIL  --text-faint (#d1d5db) on background (#ffffff)  1.47:1 < 4.50:1
      fix: --text-faint: #6b7789;  /* 4.54:1 vs #ffffff */
FAIL  --accent (#f59e0b) on background (#ffffff)  2.15:1 < 4.50:1
      fix: --accent: #a56a07;  /* 4.50:1 vs #ffffff */
PASS  color@line13 (#111827) on background (#ffffff)  17.74:1
PASS  color@line18 (#2563eb) on background (#ffffff)  5.17:1
FAIL  background@line23 (#f59e0b) on background (#ffffff)  2.15:1 < 4.50:1
      fix: --background-line23: #a56a07;  /* 4.50:1 vs #ffffff */

9 pairs: 5 passed, 4 failed (AA normal text)
```

Without `--bg`, every pair in the palette is checked against every other
(color order from the file). Captured output at AAA:

```bash
python3 contrast_doctor.py examples/palette.txt --level aaa
```

```
contrast-doctor 1.0.0 | AAA normal text, threshold 7.00:1
input: examples/palette.txt (10 pairs)

FAIL  ink (#111827) on muted (#9ca3af)  6.99:1 < 7.00:1
      fix: --ink: #111726;  /* 7.04:1 vs #9ca3af */
PASS  ink (#111827) on paper (#ffffff)  17.74:1
FAIL  ink (#111827) on brand (#2563eb)  3.43:1 < 7.00:1
      fix: --brand: #7da2f3;  /* 7.04:1 vs #2563eb */
...
10 pairs: 2 passed, 8 failed (AAA normal text)
```

Write the suggested overrides to a CSS file you can paste into your
stylesheet:

```bash
python3 contrast_doctor.py examples/theme.css --bg "#ffffff" --fix-out fixes.css
```

Captured `fixes.css`:

```css
/* contrast-doctor 1.0.0 suggested overrides (AA normal text) */
/* Review before use: suggestions shift lightness only, hue is preserved. */
:root {
  --text-muted: #6e7788; /* was #9ca3af; now 4.51:1 vs #ffffff */
  --text-faint: #6b7789; /* was #d1d5db; now 4.54:1 vs #ffffff */
  --accent: #a56a07; /* was #f59e0b; now 4.50:1 vs #ffffff */
  --background-line23: #a56a07; /* was #f59e0b; now 4.50:1 vs #ffffff */
}
```

Machine-readable report for CI dashboards and scripts:

```bash
python3 contrast_doctor.py examples/palette.json --bg "#ffffff" --json
```

```json
{
  "tool": "contrast-doctor",
  "version": "1.0.0",
  "level": "aa",
  "large_text": false,
  "threshold": 4.5,
  "input": "examples/palette.json",
  "pairs": [
    {
      "fg": {"name": "brand", "hex": "#2563eb"},
      "bg": {"name": "background", "hex": "#ffffff"},
      "ratio": 5.1686,
      "required": 4.5,
      "passes": true,
      "fix": null
    }
  ],
  "summary": {"pairs": 3, "passed": 2, "failed": 1}
}
```

## Input formats

Format is guessed from the file extension (`.css`, `.json`, anything else
is a palette); override with `--format css|palette|json`.

- **CSS**: custom properties (`--name: #rrggbb`), `color:`, `background:`,
  and `background-color:` declarations. Hex (`#rgb`, `#rrggbb`),
  `rgb()`/`rgba()`, and CSS named colors are understood. `var()`
  references are skipped.
- **Palette**: one color per line. Bare hex, or `name: #hex` / `name #hex`.
  `#`-prefixed non-hex lines and `//` lines are treated as comments.
- **JSON**: an object mapping names to hex colors, e.g.
  `{"brand": "#2563eb", "paper": "#ffffff"}`.

## Flags

| Flag | Effect |
| --- | --- |
| `--bg HEX` | Fixed background; check every color against it (repeatable) |
| `--level aa\|aaa` | WCAG conformance level (default `aa`) |
| `--large` | Use large-text thresholds (3:1 AA, 4.5:1 AAA) |
| `--min-ratio RATIO` | Custom minimum ratio, overrides `--level`/`--large` |
| `--check` | CI gate: exit 1 when any pair fails |
| `--fail-below PCT` | ratchet for `--check`: exit 1 only when the pass share drops below PCT (e.g. `--fail-below 95`); the percentage is printed in the summary either way |
| `--json` | Print the machine-readable report instead of text |
| `--fix-out FILE` | Write suggested overrides as a CSS file |
| `--format` | `auto` (default), `css`, `palette`, or `json` |

Exit codes: `0` all pairs pass (or report only), `1` failures found with
`--check`, `2` usage or input error.

## How the fix suggestions work

For a failing pair, contrast-doctor walks the foreground color's lightness
up and down in HSL space, keeping hue and saturation fixed, and picks the
smallest absolute lightness change that reaches the target ratio. When no
`--bg` is given, it tries adjusting either side of the pair and keeps the
smaller shift. If no lightness shift can reach the target (for example AAA
7:1 against a mid-gray), it says so honestly instead of guessing.

Limitations worth knowing:

- Suggestions shift lightness only. Sometimes the right design answer is a
  different hue, which the tool will not propose.
- Contrast math assumes opaque colors on opaque backgrounds. Translucency
  and text over images or gradients are out of scope.
- The tool reports numbers; it does not certify legal compliance. Treat
  thresholds as reference data for your own accessibility review.

## Development

```bash
python3 -m unittest discover -s tests -v   # 54 tests, zero dependencies
```

## License

MIT, see [LICENSE](LICENSE).
