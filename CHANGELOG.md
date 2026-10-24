# Changelog

All notable changes to this project will be documented in this file.
The format is based on Keep a Changelog, and this project adheres to
Semantic Versioning.

## [1.0.0] - 2026-10-24

### Added
- Bulk WCAG 2.1 contrast checking: relative luminance and contrast ratio
  per the WCAG formulas, checked for every foreground/background pair.
- Three input formats: CSS (custom properties plus `color`/`background`
  declarations, with hex, `rgb()`/`rgba()`, and named colors), palette
  files (one hex per line, optional names), and JSON palettes.
- Fix suggestions: for each failing pair, the nearest color (minimal
  lightness shift in HSL space, hue preserved) that passes the target
  level, printed as a paste-ready CSS variable override. Honest "no fix
  found" when the target is unreachable by lightness shift alone.
- CLI flags: `--bg` (repeatable fixed backgrounds), `--level aa|aaa`,
  `--large` (large-text thresholds), `--min-ratio` (custom threshold),
  `--check` (CI gate, exit 1 on failures), `--json` (machine-readable
  report), `--fix-out` (write suggested overrides as CSS),
  `--format` (input format override).
- Exit codes: 0 all pass, 1 failures with `--check`, 2 usage/input error.
- 54-test suite covering parsing, WCAG math, thresholds, fix quality,
  CLI behavior, exit codes, and an em-dash scan of repo text.
