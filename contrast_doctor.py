#!/usr/bin/env python3
"""contrast-doctor: bulk WCAG contrast checker with concrete fix suggestions.

Reads colors from CSS files, plain palette files, or JSON palettes, checks
every foreground/background pair against WCAG 2.1 contrast thresholds, and
for each failing pair suggests the nearest adjusted color (minimal lightness
shift in HSL space, hue preserved) that passes. Zero dependencies.

Usage:
    python3 contrast_doctor.py styles.css
    python3 contrast_doctor.py palette.txt --bg "#ffffff" --level aaa
    python3 contrast_doctor.py theme.css --check --json --fix-out fixes.css
"""

from __future__ import annotations

import argparse
import json
import os
import math
import re
import sys
from collections import namedtuple

__version__ = "1.0.0"

Color = namedtuple("Color", ["name", "hex", "line"])


# ---------------------------------------------------------------------------
# Color primitives
# ---------------------------------------------------------------------------

_HEX_RE = re.compile(r"^#?([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
_RGB_FN_RE = re.compile(
    r"rgba?\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})"
    r"(?:\s*,\s*[\d.]+\s*)?\)"
)
_OKLCH_FN_RE = re.compile(r"oklch\(([^)]*)\)", re.IGNORECASE)
_COLOR_MIX_FN = "color-mix("


def normalize_hex(value):
    """Return ``#rrggbb`` lowercase form, or raise ValueError."""
    if not isinstance(value, str):
        raise ValueError("color must be a string, got %r" % (value,))
    text = value.strip()
    match = _HEX_RE.match(text)
    if not match:
        raise ValueError("not a hex color: %r" % (value,))
    digits = match.group(1)
    if len(digits) == 3:
        digits = "".join(ch * 2 for ch in digits)
    return "#" + digits.lower()


def hex_to_rgb(value):
    """Return ``(r, g, b)`` floats in 0..1 for a hex color."""
    digits = normalize_hex(value)[1:]
    return tuple(int(digits[i:i + 2], 16) / 255.0 for i in (0, 2, 4))


def rgb_to_hex(r, g, b):
    """Return ``#rrggbb`` for 0..1 channel floats."""
    clamp = lambda c: max(0, min(255, int(round(c * 255))))
    return "#%02x%02x%02x" % (clamp(r), clamp(g), clamp(b))


def relative_luminance(rgb):
    """WCAG 2.1 relative luminance for an ``(r, g, b)`` 0..1 triple."""
    def linearize(channel):
        if channel <= 0.03928:
            return channel / 12.92
        return ((channel + 0.055) / 1.055) ** 2.4

    r, g, b = (linearize(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(hex1, hex2):
    """WCAG 2.1 contrast ratio between two hex colors, 1.0 to 21.0."""
    lum1 = relative_luminance(hex_to_rgb(hex1))
    lum2 = relative_luminance(hex_to_rgb(hex2))
    lighter = max(lum1, lum2)
    darker = min(lum1, lum2)
    return (lighter + 0.05) / (darker + 0.05)


def rgb_to_hsl(r, g, b):
    """Return ``(h, s, l)`` with h in 0..1 and s, l in 0..1."""
    mx = max(r, g, b)
    mn = min(r, g, b)
    light = (mx + mn) / 2.0
    if mx == mn:
        return (0.0, 0.0, light)
    delta = mx - mn
    sat = delta / (2.0 - mx - mn) if light > 0.5 else delta / (mx + mn)
    if mx == r:
        hue = (g - b) / delta + (6.0 if g < b else 0.0)
    elif mx == g:
        hue = (b - r) / delta + 2.0
    else:
        hue = (r - g) / delta + 4.0
    return (hue / 6.0, sat, light)


def hsl_to_rgb(h, s, light):
    """Return ``(r, g, b)`` 0..1 floats for ``(h, s, l)`` inputs."""
    if s == 0.0:
        return (light, light, light)

    def hue_to_rgb(p, q, t):
        t = t % 1.0
        if t < 1.0 / 6.0:
            return p + (q - p) * 6.0 * t
        if t < 0.5:
            return q
        if t < 2.0 / 3.0:
            return p + (q - p) * (2.0 / 3.0 - t) * 6.0
        return p

    q = light * (1.0 + s) if light < 0.5 else light + s - light * s
    p = 2.0 * light - q
    return (
        hue_to_rgb(p, q, h + 1.0 / 3.0),
        hue_to_rgb(p, q, h),
        hue_to_rgb(p, q, h - 1.0 / 3.0),
    )


# ---------------------------------------------------------------------------
# CSS named colors (CSS Color Module Level 4)
# ---------------------------------------------------------------------------

NAMED_COLORS = {
    "aliceblue": "#f0f8ff", "antiquewhite": "#faebd7", "aqua": "#00ffff",
    "aquamarine": "#7fffd4", "azure": "#f0ffff", "beige": "#f5f5dc",
    "bisque": "#ffe4c4", "black": "#000000", "blanchedalmond": "#ffebcd",
    "blue": "#0000ff", "blueviolet": "#8a2be2", "brown": "#a52a2a",
    "burlywood": "#deb887", "cadetblue": "#5f9ea0", "chartreuse": "#7fff00",
    "chocolate": "#d2691e", "coral": "#ff7f50", "cornflowerblue": "#6495ed",
    "cornsilk": "#fff8dc", "crimson": "#dc143c", "cyan": "#00ffff",
    "darkblue": "#00008b", "darkcyan": "#008b8b", "darkgoldenrod": "#b8860b",
    "darkgray": "#a9a9a9", "darkgrey": "#a9a9a9", "darkgreen": "#006400",
    "darkkhaki": "#bdb76b", "darkmagenta": "#8b008b",
    "darkolivegreen": "#556b2f", "darkorange": "#ff8c00",
    "darkorchid": "#9932cc", "darkred": "#8b0000", "darksalmon": "#e9967a",
    "darkseagreen": "#8fbc8f", "darkslateblue": "#483d8b",
    "darkslategray": "#2f4f4f", "darkslategrey": "#2f4f4f",
    "darkturquoise": "#00ced1", "darkviolet": "#9400d3",
    "deeppink": "#ff1493", "deepskyblue": "#00bfff", "dimgray": "#696969",
    "dimgrey": "#696969", "dodgerblue": "#1e90ff", "firebrick": "#b22222",
    "floralwhite": "#fffaf0", "forestgreen": "#228b22", "fuchsia": "#ff00ff",
    "gainsboro": "#dcdcdc", "ghostwhite": "#f8f8ff", "gold": "#ffd700",
    "goldenrod": "#daa520", "gray": "#808080", "grey": "#808080",
    "green": "#008000", "greenyellow": "#adff2f", "honeydew": "#f0fff0",
    "hotpink": "#ff69b4", "indianred": "#cd5c5c", "indigo": "#4b0082",
    "ivory": "#fffff0", "khaki": "#f0e68c", "lavender": "#e6e6fa",
    "lavenderblush": "#fff0f5", "lawngreen": "#7cfc00",
    "lemonchiffon": "#fffacd", "lightblue": "#add8e6", "lightcoral": "#f08080",
    "lightcyan": "#e0ffff", "lightgoldenrodyellow": "#fafad2",
    "lightgray": "#d3d3d3", "lightgrey": "#d3d3d3", "lightgreen": "#90ee90",
    "lightpink": "#ffb6c1", "lightsalmon": "#ffa07a",
    "lightseagreen": "#20b2aa", "lightskyblue": "#87cefa",
    "lightslategray": "#778899", "lightslategrey": "#778899",
    "lightsteelblue": "#b0c4de", "lightyellow": "#ffffe0", "lime": "#00ff00",
    "limegreen": "#32cd32", "linen": "#faf0e6", "magenta": "#ff00ff",
    "maroon": "#800000", "mediumaquamarine": "#66cdaa",
    "mediumblue": "#0000cd", "mediumorchid": "#ba55d3",
    "mediumpurple": "#9370db", "mediumseagreen": "#3cb371",
    "mediumslateblue": "#7b68ee", "mediumspringgreen": "#00fa9a",
    "mediumturquoise": "#48d1cc", "mediumvioletred": "#c71585",
    "midnightblue": "#191970", "mintcream": "#f5fffa", "mistyrose": "#ffe4e1",
    "moccasin": "#ffe4b5", "navajowhite": "#ffdead", "navy": "#000080",
    "oldlace": "#fdf5e6", "olive": "#808000", "olivedrab": "#6b8e23",
    "orange": "#ffa500", "orangered": "#ff4500", "orchid": "#da70d6",
    "palegoldenrod": "#eee8aa", "palegreen": "#98fb98",
    "paleturquoise": "#afeeee", "palevioletred": "#db7093",
    "papayawhip": "#ffefd5", "peachpuff": "#ffdab9", "peru": "#cd853f",
    "pink": "#ffc0cb", "plum": "#dda0dd", "powderblue": "#b0e0e6",
    "purple": "#800080", "rebeccapurple": "#663399", "red": "#ff0000",
    "rosybrown": "#bc8f8f", "royalblue": "#4169e1", "saddlebrown": "#8b4513",
    "salmon": "#fa8072", "sandybrown": "#f4a460", "seagreen": "#2e8b57",
    "seashell": "#fff5ee", "sienna": "#a0522d", "silver": "#c0c0c0",
    "skyblue": "#87ceeb", "slateblue": "#6a5acd", "slategray": "#708090",
    "slategrey": "#708090", "snow": "#fffafa", "springgreen": "#00ff7f",
    "steelblue": "#4682b4", "tan": "#d2b48c", "teal": "#008080",
    "thistle": "#d8bfd8", "tomato": "#ff6347", "turquoise": "#40e0d0",
    "violet": "#ee82ee", "wheat": "#f5deb3", "white": "#ffffff",
    "whitesmoke": "#f5f5f5", "yellow": "#ffff00", "yellowgreen": "#9acd32",
}


# ---------------------------------------------------------------------------
# Input parsing
# ---------------------------------------------------------------------------

class InputError(Exception):
    """Raised when an input file cannot be read or parsed."""


def _oklch_to_srgb_hex(l_raw, c_raw, h_raw):
    """Convert OKLCH components to ``#rrggbb``, clamping out-of-gamut values.

    Accepts lightness as 0-1 or a percentage. Returns None for components
    that do not parse, or an alpha channel (only opaque colors resolve).
    """
    try:
        l_text, c_text, h_text = l_raw.strip(), c_raw.strip(), h_raw.strip()
        if "/" in l_text or "/" in c_text or "/" in h_text:
            return None
        l_value = float(l_text[:-1]) / 100.0 if l_text.endswith("%") else float(l_text)
        c_value = float(c_text)
        h_value = float(h_text) % 360.0
    except ValueError:
        return None
    a = c_value * math.cos(math.radians(h_value))
    b = c_value * math.sin(math.radians(h_value))
    # OKLab -> LMS -> linear sRGB (CSS Color 4 reference matrices)
    l_ = l_value + 0.3963377774 * a + 0.2158037573 * b
    m_ = l_value - 0.1055613458 * a - 0.0638541728 * b
    s_ = l_value - 0.0894841775 * a - 1.2914855480 * b
    l_, m_, s_ = l_ ** 3, m_ ** 3, s_ ** 3
    r_lin = +4.0767416621 * l_ - 3.3077115913 * m_ + 0.2309699292 * s_
    g_lin = -1.2684380046 * l_ + 2.6097574011 * m_ - 0.3413193965 * s_
    b_lin = -0.0041960863 * l_ - 0.7034186147 * m_ + 1.7076147010 * s_

    def encode(channel):
        channel = max(0.0, min(1.0, channel))
        return round(
            12.92 * channel
            if channel <= 0.0031308
            else 1.055 * channel ** (1 / 2.4) - 0.055
        ) * 255

    return "#%02x%02x%02x" % (encode(r_lin), encode(g_lin), encode(b_lin))


def _resolve_oklch(value):
    """Resolve an ``oklch(...)`` call found in *value* to ``#rrggbb`` or None."""
    match = _OKLCH_FN_RE.search(value)
    if not match:
        return None
    parts = match.group(1).split()
    if len(parts) != 3:
        return None
    return _oklch_to_srgb_hex(*parts)


def _matching_paren(value, start):
    """Index of the ``)`` closing the ``(`` at *start*, or -1."""
    depth = 0
    for i in range(start, len(value)):
        if value[i] == "(":
            depth += 1
        elif value[i] == ")":
            depth -= 1
            if depth == 0:
                return i
    return -1


def _resolve_color_mix(value):
    """Resolve ``color-mix(in srgb, A p1, B p2)`` to ``#rrggbb`` or None.

    Only ``in srgb`` with two opaque colors mixes; anything else returns
    None. Weights are normalized like CSS: one missing weight takes the
    remainder, both missing means 50/50.
    """
    head = value.lower().find(_COLOR_MIX_FN)
    if head < 0:
        return None
    open_at = head + len(_COLOR_MIX_FN) - 1
    close_at = _matching_paren(value, open_at)
    if close_at < 0:
        return None
    inner = value[open_at + 1 : close_at]
    if not inner.lower().lstrip().startswith("in srgb"):
        return None
    body = inner[len("in srgb") :].lstrip()
    if not body.startswith(","):
        return None
    parts = body[1:].split(",")
    if len(parts) != 2:
        return None
    sides = []
    for part in parts:
        part = part.strip()
        match = re.match(r"^(.+?)\s+([\d.]+)%$", part)
        if match:
            sides.append((match.group(1).strip(), float(match.group(2))))
        else:
            sides.append((part, None))
    (a_text, a_weight), (b_text, b_weight) = sides
    if a_weight is None and b_weight is None:
        a_weight = b_weight = 50.0
    elif a_weight is None:
        a_weight = 100.0 - b_weight
    elif b_weight is None:
        b_weight = 100.0 - a_weight
    # a weight over 100 leaves its neighbour negative; CSS clamps the
    # remainder to 0 and normalises whatever sum is left
    a_weight = max(0.0, min(100.0, a_weight))
    b_weight = max(0.0, min(100.0, b_weight))
    total = a_weight + b_weight
    if total <= 0:
        return None
    first, second = _color_from_token(a_text), _color_from_token(b_text)
    if not first or not second:
        return None
    wa, wb = a_weight / total, b_weight / total
    mixed = bytes(
        round(wa * f + wb * s)
        for f, s in zip(bytes.fromhex(first[1:]), bytes.fromhex(second[1:]))
    )
    return "#%02x%02x%02x" % tuple(mixed)


def _color_from_token(token):
    """Resolve a CSS color token to ``#rrggbb`` or return None.

    Accepts hex colors, ``rgb()``/``rgba()`` functions (alpha is ignored),
    ``oklch()`` (converted to sRGB, out-of-gamut clamped), simple
    ``color-mix(in srgb, ...)`` expressions, and CSS named colors. Anything
    else (var(), gradients, keywords like ``inherit``) returns None.
    """
    token = token.strip().rstrip(";").strip()
    if not token:
        return None
    if token.startswith("#"):
        try:
            return normalize_hex(token)
        except ValueError:
            return None
    rgb_match = _RGB_FN_RE.match(token)
    if rgb_match:
        try:
            channels = [int(c) for c in rgb_match.groups()]
        except ValueError:
            return None
        if any(c < 0 or c > 255 for c in channels):
            return None
        return "#%02x%02x%02x" % tuple(channels)
    lowered = token.lower()
    if lowered in NAMED_COLORS:
        return NAMED_COLORS[lowered]
    if lowered.startswith("oklch("):
        return _resolve_oklch(token)
    if lowered.startswith("color-mix("):
        return _resolve_color_mix(token)
    return None


def _first_color_in_value(value):
    """Extract the first color token from a CSS declaration value."""
    # Functional notations contain spaces, commas and parentheses, so they
    # must match against the whole value before the token split shreds them.
    mix = _resolve_color_mix(value)
    if mix:
        return mix
    oklch = _resolve_oklch(value)
    if oklch:
        return oklch
    for token in re.split(r"[\s,()/]+", value):
        if not token or token in ("!", "important"):
            continue
        resolved = _color_from_token(token)
        if resolved:
            return resolved
        if token.startswith("rgb"):
            match = _RGB_FN_RE.search(value)
            if match:
                channels = [int(c) for c in match.groups()]
                return "#%02x%02x%02x" % tuple(channels)
    return None


def parse_css(text):
    """Parse colors from CSS text.

    Collects custom properties (``--name: <color>``) and ``color``,
    ``background-color``, and ``background`` declarations. Returns a list of
    ``Color`` tuples with 1-based line numbers. Declarations that carry no
    recognizable color are skipped silently.
    """
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    colors = []
    custom_prop_re = re.compile(r"(--[\w-]+)\s*:\s*([^;{}]+)")
    decl_re = re.compile(
        r"(?:^|[;{}])\s*(color|background-color|background)\s*:\s*([^;{}]+)",
        re.IGNORECASE,
    )
    for lineno, line in enumerate(text.splitlines(), start=1):
        for match in custom_prop_re.finditer(line):
            name, value = match.group(1), match.group(2)
            resolved = _first_color_in_value(value)
            if resolved:
                colors.append(Color(name=name, hex=resolved, line=lineno))
        for match in decl_re.finditer(line):
            prop, value = match.group(1).lower(), match.group(2)
            resolved = _first_color_in_value(value)
            if resolved:
                colors.append(
                    Color(name="%s@line%d" % (prop, lineno),
                          hex=resolved, line=lineno)
                )
    return colors


def parse_palette(text):
    """Parse a palette file: one color per line.

    Each line may be a bare hex color (``#rgb`` or ``#rrggbb``), or a named
    entry as ``name: #hex`` or ``name #hex``. Blank lines, ``//`` comments,
    and ``#``-prefixed lines that are not valid hex are skipped.
    """
    colors = []
    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("//"):
            continue
        if line.startswith("#"):
            try:
                hex_value = normalize_hex(line)
            except ValueError:
                continue  # a # comment, not a color
            colors.append(Color(name="color%d" % (len(colors) + 1),
                                hex=hex_value, line=lineno))
            continue
        name = None
        token = line
        for sep in (":", " ", "\t"):
            if sep in line:
                maybe_name, maybe_token = line.split(sep, 1)
                maybe_name, maybe_token = (maybe_name.strip(),
                                           maybe_token.strip())
                if maybe_name and maybe_token:
                    name = re.sub(r"[^a-zA-Z0-9_-]+", "-",
                                  maybe_name).strip("-").lower()
                    token = maybe_token
                    break
        try:
            hex_value = normalize_hex(token)
        except ValueError:
            raise InputError("line %d: not a color: %r" % (lineno, raw))
        if not name:
            name = "color%d" % (len(colors) + 1)
        colors.append(Color(name=name, hex=hex_value, line=lineno))
    return colors


def parse_json_palette(text):
    """Parse a JSON palette: an object mapping names to hex colors."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise InputError("invalid JSON: %s" % (exc,))
    if not isinstance(data, dict):
        raise InputError("JSON palette must be an object of name -> hex color")
    colors = []
    for lineno, (name, value) in enumerate(data.items(), start=1):
        if not isinstance(value, str):
            raise InputError("entry %r: color must be a string" % (name,))
        try:
            hex_value = normalize_hex(value)
        except ValueError:
            raise InputError("entry %r: not a hex color: %r" % (name, value))
        clean = re.sub(r"[^a-zA-Z0-9_-]+", "-", str(name)).strip("-").lower()
        colors.append(Color(name=clean or "color%d" % lineno,
                            hex=hex_value, line=lineno))
    return colors


def detect_format(path):
    """Guess the input format from the file extension."""
    lower = path.lower()
    if lower.endswith(".css"):
        return "css"
    if lower.endswith(".json"):
        return "json"
    return "palette"


def load_input(path, fmt="auto"):
    """Read and parse one input file. Raises InputError on problems."""
    if fmt == "auto":
        fmt = detect_format(path)
    try:
        with open(path, "r", encoding="utf-8") as handle:
            text = handle.read()
    except OSError as exc:
        raise InputError("cannot read %r: %s" % (path, exc))
    if fmt == "css":
        colors = parse_css(text)
    elif fmt == "json":
        colors = parse_json_palette(text)
    elif fmt == "palette":
        colors = parse_palette(text)
    else:
        raise InputError("unknown format %r" % (fmt,))
    if not colors:
        raise InputError("%s: no colors found" % (path,))
    return colors


# ---------------------------------------------------------------------------
# WCAG thresholds and fix suggestions
# ---------------------------------------------------------------------------

def threshold_for(level, large_text=False):
    """Return the WCAG 2.1 contrast threshold for a level and text size."""
    table = {
        ("aa", False): 4.5,
        ("aa", True): 3.0,
        ("aaa", False): 7.0,
        ("aaa", True): 4.5,
    }
    try:
        return table[(level, large_text)]
    except KeyError:
        raise ValueError("unknown level %r" % (level,))


def level_label(level, large_text=False):
    size = "large text" if large_text else "normal text"
    return "%s %s" % (level.upper(), size)


def suggest_fix(fg_hex, bg_hex, target_ratio, step=0.0025):
    """Suggest the nearest color to ``fg_hex`` that passes ``target_ratio``.

    Walks lightness up and down in HSL space (hue and saturation preserved)
    and returns ``(new_hex, new_ratio)`` for the smallest absolute lightness
    shift that reaches the target. Returns None when the target is
    unreachable by adjusting the foreground alone (for example AAA 7:1
    against a mid-gray background). The returned hex is re-verified to pass
    after quantization.
    """
    fg_hex = normalize_hex(fg_hex)
    bg_hex = normalize_hex(bg_hex)
    if contrast_ratio(fg_hex, bg_hex) >= target_ratio:
        return (fg_hex, contrast_ratio(fg_hex, bg_hex))
    r, g, b = hex_to_rgb(fg_hex)
    hue, sat, light = rgb_to_hsl(r, g, b)
    best = None  # (delta_lightness, hex, ratio)
    for direction in (-1.0, 1.0):
        lightness = light + direction * step
        while 0.0 <= lightness <= 1.0:
            candidate = rgb_to_hex(*hsl_to_rgb(hue, sat, lightness))
            ratio = contrast_ratio(candidate, bg_hex)
            if ratio >= target_ratio:
                delta = abs(lightness - light)
                if best is None or delta < best[0]:
                    best = (delta, candidate, ratio)
                break
            lightness += direction * step
    return None if best is None else (best[1], best[2])


# ---------------------------------------------------------------------------
# Pair checking
# ---------------------------------------------------------------------------

def check_pairs(colors, backgrounds, target_ratio):
    """Check every foreground/background pair.

    ``colors`` is the full color list; ``backgrounds`` is None to check all
    unordered pairs, or a list of hex colors to use as fixed backgrounds.
    Returns a list of dicts with fg, bg, ratio, passes, and fix details.
    """
    results = []
    if backgrounds:
        pairs = []
        for fg in colors:
            fg_hex = normalize_hex(fg.hex)
            for bg_hex in backgrounds:
                if fg_hex == bg_hex:
                    continue
                pairs.append((Color(fg.name, fg_hex, fg.line),
                              Color(name="background", hex=bg_hex, line=0),
                              True))
    else:
        pairs = []
        normalized = [Color(c.name, normalize_hex(c.hex), c.line)
                      for c in colors]
        for i, first in enumerate(normalized):
            for second in normalized[i + 1:]:
                if first.hex == second.hex:
                    continue
                pairs.append((first, second, False))

    for fg, bg, fg_is_text in pairs:
        ratio = contrast_ratio(fg.hex, bg.hex)
        passes = ratio >= target_ratio
        fix_hex = fix_ratio = fixed_name = None
        if not passes:
            if fg_is_text:
                # The foreground is the text color: adjust it, keep the bg.
                sides = [(fg, bg)]
            else:
                # Try adjusting either side; keep the smaller lightness shift.
                sides = [(fg, bg), (bg, fg)]
            candidates = []
            for side_fg, side_bg in sides:
                suggestion = suggest_fix(side_fg.hex, side_bg.hex,
                                         target_ratio)
                if suggestion:
                    old_l = rgb_to_hsl(*hex_to_rgb(side_fg.hex))[2]
                    new_l = rgb_to_hsl(*hex_to_rgb(suggestion[0]))[2]
                    candidates.append((abs(new_l - old_l), side_fg,
                                       suggestion[0], suggestion[1]))
            if candidates:
                candidates.sort(key=lambda c: c[0])
                _, fixed, fix_hex, fix_ratio = candidates[0]
                fixed_name = fixed.name
        results.append({
            "fg": fg,
            "bg": bg,
            "ratio": ratio,
            "required": target_ratio,
            "passes": passes,
            "fix_hex": fix_hex,
            "fix_ratio": fix_ratio,
            "fixed_name": fixed_name,
        })
    return results


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

_CSS_VAR_RE = re.compile(r"^--[A-Za-z0-9_-]+$")


def sanitize_var_name(name, fallback_index):
    """Return a usable CSS custom property name for a color name."""
    if _CSS_VAR_RE.match(name):
        return name
    clean = re.sub(r"[^A-Za-z0-9_-]+", "-", name).strip("-")
    if not clean.startswith("--"):
        clean = "--" + clean
    if _CSS_VAR_RE.match(clean):
        return clean
    return "--contrast-doctor-fix-%d" % fallback_index


def render_text(results, label, source_desc):
    """Render a human-readable report."""
    lines = []
    lines.append("contrast-doctor %s | %s, threshold %.2f:1"
                 % (__version__, label, results[0]["required"]
                    if results else 0.0))
    lines.append("input: %s (%d pairs)" % (source_desc, len(results)))
    lines.append("")
    for res in results:
        status = "PASS" if res["passes"] else "FAIL"
        fg, bg = res["fg"], res["bg"]
        if res["passes"]:
            lines.append("PASS  %s (%s) on %s (%s)  %.2f:1"
                         % (fg.name, fg.hex, bg.name, bg.hex, res["ratio"]))
        else:
            lines.append("FAIL  %s (%s) on %s (%s)  %.2f:1 < %.2f:1"
                         % (fg.name, fg.hex, bg.name, bg.hex, res["ratio"],
                            res["required"]))
            if res["fix_hex"]:
                var = sanitize_var_name(res["fixed_name"] or fg.name, 0)
                lines.append("      fix: %s: %s;  /* %.2f:1 vs %s */"
                             % (var, res["fix_hex"], res["fix_ratio"], bg.hex))
            else:
                lines.append("      fix: none found by lightness shift; "
                             "pick a different hue")
    passed = sum(1 for r in results if r["passes"])
    failed = len(results) - passed
    lines.append("")
    lines.append("%d pairs: %d passed, %d failed (%s)"
                 % (len(results), passed, failed, label))
    return "\n".join(lines)


def report_to_json(results, label, source_desc, args):
    """Build the machine-readable report dict."""
    pairs = []
    for res in results:
        pairs.append({
            "fg": {"name": res["fg"].name, "hex": res["fg"].hex},
            "bg": {"name": res["bg"].name, "hex": res["bg"].hex},
            "ratio": round(res["ratio"], 4),
            "required": res["required"],
            "passes": res["passes"],
            "fix": ({"hex": res["fix_hex"],
                     "ratio": round(res["fix_ratio"], 4),
                     "variable": sanitize_var_name(
                         res["fixed_name"] or res["fg"].name, 0)}
                    if res["fix_hex"] else None),
        })
    passed = sum(1 for r in results if r["passes"])
    return {
        "tool": "contrast-doctor",
        "version": __version__,
        "level": args.level,
        "large_text": args.large,
        "threshold": results[0]["required"] if results else None,
        "input": source_desc,
        "pairs": pairs,
        "summary": {
            "pairs": len(results),
            "passed": passed,
            "failed": len(results) - passed,
        },
    }


def write_fix_file(path, results, label):
    """Write suggested overrides as a CSS file. Returns the count written."""
    lines = [
        "/* contrast-doctor %s suggested overrides (%s) */"
        % (__version__, label),
        "/* Review before use: suggestions shift lightness only, "
        "hue is preserved. */",
        ":root {",
    ]
    used = set()
    index = 0
    written = 0
    for res in results:
        if res["passes"] or not res["fix_hex"]:
            continue
        index += 1
        var = sanitize_var_name(res["fixed_name"] or res["fg"].name, index)
        while var in used:
            index += 1
            var = sanitize_var_name(res["fixed_name"] or res["fg"].name,
                                    index)
        used.add(var)
        lines.append("  %s: %s; /* was %s; now %.2f:1 vs %s */"
                     % (var, res["fix_hex"], res["fg"].hex, res["fix_ratio"],
                        res["bg"].hex))
        written += 1
    lines.append("}")
    lines.append("")
    try:
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("\n".join(lines))
    except OSError as exc:
        raise InputError("cannot write %r: %s" % (path, exc))
    return written


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser():
    parser = argparse.ArgumentParser(
        prog="contrast-doctor",
        description="Bulk WCAG contrast checker with fix suggestions. "
                    "Reads colors from CSS, palette, or JSON files, checks "
                    "every foreground/background pair, and suggests the "
                    "nearest passing color for each failure.",
    )
    parser.add_argument("inputs", nargs="+",
                        help="CSS, palette, or JSON files to check")
    parser.add_argument("--format", default="auto",
                        choices=["auto", "css", "palette", "json"],
                        help="input format (default: guessed from extension)")
    parser.add_argument("--bg", action="append", default=[],
                        metavar="HEX",
                        help="fixed background color; check every color "
                             "against it (repeatable)")
    parser.add_argument("--level", default="aa", choices=["aa", "aaa"],
                        help="WCAG conformance level (default: aa)")
    parser.add_argument("--large", action="store_true",
                        help="use large-text thresholds (3:1 AA, 4.5:1 AAA)")
    parser.add_argument("--min-ratio", type=float, default=None,
                        metavar="RATIO",
                        help="custom minimum ratio, overrides --level/--large")
    parser.add_argument("--check", action="store_true",
                        help="CI gate: exit 1 when any pair fails")
    parser.add_argument("--json", action="store_true",
                        help="print machine-readable JSON report")
    parser.add_argument("--fix-out", default=None, metavar="FILE",
                        help="write suggested CSS overrides to FILE")
    parser.add_argument("--version", action="version",
                        version="contrast-doctor " + __version__)
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.min_ratio is not None:
        if not 1.0 <= args.min_ratio <= 21.0:
            parser.error("--min-ratio must be between 1.0 and 21.0")
        target = args.min_ratio
        label = "custom threshold"
    else:
        try:
            target = threshold_for(args.level, args.large)
        except ValueError as exc:
            parser.error(str(exc))
        label = level_label(args.level, args.large)

    backgrounds = []
    for raw in args.bg:
        try:
            backgrounds.append(normalize_hex(raw))
        except ValueError:
            print("error: --bg %r is not a valid hex color" % raw,
                  file=sys.stderr)
            return 2

    all_colors = []
    source_desc = ", ".join(args.inputs)
    try:
        for path in args.inputs:
            all_colors.extend(load_input(path, args.format))
    except InputError as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 2

    results = check_pairs(all_colors, backgrounds or None, target)
    if not results:
        print("no pairs to check: need at least two distinct colors")
        return 0
    failed = sum(1 for r in results if not r["passes"])

    if args.fix_out:
        try:
            written = write_fix_file(args.fix_out, results, label)
        except InputError as exc:
            print("error: %s" % exc, file=sys.stderr)
            return 2
        if not args.json:
            print("wrote %d suggested override(s) to %s"
                  % (written, args.fix_out))

    if args.json:
        print(json.dumps(report_to_json(results, label, source_desc, args),
                         indent=2))
    else:
        print(render_text(results, label, source_desc))

    if args.check and failed:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
