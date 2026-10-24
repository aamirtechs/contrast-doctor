"""Tests for contrast-doctor. Run with: python3 -m unittest discover -s tests -v"""

import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import contrast_doctor
from contrast_doctor import (
    Color, InputError, check_pairs, contrast_ratio, detect_format,
    hex_to_rgb, load_input, main, normalize_hex, parse_css, parse_json_palette,
    parse_palette, relative_luminance, render_text, report_to_json,
    rgb_to_hex, rgb_to_hsl, hsl_to_rgb, sanitize_var_name, suggest_fix,
    threshold_for, write_fix_file,
    _resolve_color_mix, _resolve_oklch,
)


class HexParsingTests(unittest.TestCase):
    def test_six_digit(self):
        self.assertEqual(normalize_hex("#1D4ED8"), "#1d4ed8")

    def test_three_digit_expands(self):
        self.assertEqual(normalize_hex("#abc"), "#aabbcc")

    def test_without_hash(self):
        self.assertEqual(normalize_hex("ffffff"), "#ffffff")

    def test_invalid_rejected(self):
        for bad in ["#12", "#12345", "#gggggg", "red-ish", "", None, 123]:
            with self.assertRaises(ValueError, msg=repr(bad)):
                normalize_hex(bad)

    def test_round_trip(self):
        self.assertEqual(rgb_to_hex(*hex_to_rgb("#1d4ed8")), "#1d4ed8")


class LuminanceTests(unittest.TestCase):
    def test_black_is_zero(self):
        self.assertAlmostEqual(relative_luminance((0.0, 0.0, 0.0)), 0.0)

    def test_white_is_one(self):
        self.assertAlmostEqual(relative_luminance((1.0, 1.0, 1.0)), 1.0)

    def test_black_white_ratio_is_21(self):
        self.assertAlmostEqual(contrast_ratio("#000000", "#ffffff"), 21.0)

    def test_same_color_ratio_is_1(self):
        self.assertAlmostEqual(contrast_ratio("#1d4ed8", "#1D4ED8"), 1.0)

    def test_known_mid_gray_ratio(self):
        # #767676 on white is the textbook 4.54:1 AA boundary example.
        self.assertAlmostEqual(contrast_ratio("#767676", "#ffffff"),
                               4.54, places=2)

    def test_ratio_is_symmetric(self):
        self.assertAlmostEqual(contrast_ratio("#ff0000", "#0000ff"),
                               contrast_ratio("#0000ff", "#ff0000"))


class ThresholdTests(unittest.TestCase):
    def test_table(self):
        self.assertEqual(threshold_for("aa", False), 4.5)
        self.assertEqual(threshold_for("aa", True), 3.0)
        self.assertEqual(threshold_for("aaa", False), 7.0)
        self.assertEqual(threshold_for("aaa", True), 4.5)

    def test_unknown_level(self):
        with self.assertRaises(ValueError):
            threshold_for("aax")


class HslTests(unittest.TestCase):
    def test_round_trip(self):
        for hex_value in ["#1d4ed8", "#ff0000", "#808080", "#123456"]:
            r, g, b = hex_to_rgb(hex_value)
            r2, g2, b2 = hsl_to_rgb(*rgb_to_hsl(r, g, b))
            self.assertEqual(rgb_to_hex(r2, g2, b2), hex_value)

    def test_gray_has_no_saturation(self):
        h, s, l = rgb_to_hsl(*hex_to_rgb("#808080"))
        self.assertAlmostEqual(s, 0.0)
        self.assertAlmostEqual(l, 0.5019, places=3)


class SuggestFixTests(unittest.TestCase):
    def test_fix_passes_target(self):
        new_hex, new_ratio = suggest_fix("#9ca3af", "#ffffff", 4.5)
        self.assertGreaterEqual(new_ratio, 4.5)
        self.assertGreaterEqual(contrast_ratio(new_hex, "#ffffff"), 4.5)

    def test_fix_preserves_hue_roughly(self):
        old_h = rgb_to_hsl(*hex_to_rgb("#9ca3af"))[0]
        new_hex, _ = suggest_fix("#9ca3af", "#ffffff", 4.5)
        new_h = rgb_to_hsl(*hex_to_rgb(new_hex))[0]
        self.assertAlmostEqual(old_h, new_h, places=1)

    def test_fix_is_minimal_shift(self):
        # The suggested color should be darker-but-close, not pure black.
        new_hex, _ = suggest_fix("#9ca3af", "#ffffff", 4.5)
        self.assertNotEqual(new_hex, "#000000")
        old_l = rgb_to_hsl(*hex_to_rgb("#9ca3af"))[2]
        new_l = rgb_to_hsl(*hex_to_rgb(new_hex))[2]
        self.assertLess(abs(new_l - old_l), 0.35)

    def test_already_passing_returns_original(self):
        new_hex, new_ratio = suggest_fix("#000000", "#ffffff", 4.5)
        self.assertEqual(new_hex, "#000000")

    def test_unreachable_returns_none(self):
        # Nothing reaches AAA 7:1 against mid-gray #808080.
        self.assertIsNone(suggest_fix("#000000", "#808080", 7.0))
        self.assertIsNone(suggest_fix("#ffffff", "#808080", 7.0))

    def test_dark_background_lightens(self):
        new_hex, new_ratio = suggest_fix("#555555", "#111111", 4.5)
        self.assertGreaterEqual(new_ratio, 4.5)
        old_l = rgb_to_hsl(*hex_to_rgb("#555555"))[2]
        new_l = rgb_to_hsl(*hex_to_rgb(new_hex))[2]
        self.assertGreater(new_l, old_l)


class CssParsingTests(unittest.TestCase):
    CSS = """
    :root {
      --brand-700: #1d4ed8;
      --text-muted: #9ca3af;
      --surface: rgb(255, 255, 255);
      --alias: var(--brand-700);
    }
    body { color: #111111; background-color: white; }
    a { color: #2563eb; background: #ffffff url(x.png); }
    """

    def test_custom_properties(self):
        colors = parse_css(self.CSS)
        by_name = {c.name: c.hex for c in colors}
        self.assertEqual(by_name["--brand-700"], "#1d4ed8")
        self.assertEqual(by_name["--text-muted"], "#9ca3af")
        self.assertEqual(by_name["--surface"], "#ffffff")
        self.assertNotIn("--alias", by_name)

    def test_declarations(self):
        colors = parse_css(self.CSS)
        by_name = {c.name: c.hex for c in colors}
        self.assertEqual(by_name["color@line8"], "#111111")
        self.assertEqual(by_name["background-color@line8"], "#ffffff")
        self.assertEqual(by_name["color@line9"], "#2563eb")

    def test_comments_ignored(self):
        colors = parse_css("/* --fake: #123456; */\n:root { --real: #abcdef; }")
        self.assertEqual([c.hex for c in colors], ["#abcdef"])

    def test_line_numbers(self):
        colors = parse_css(":root {\n  --a: #111111;\n}")
        self.assertEqual(colors[0].line, 2)


class PaletteParsingTests(unittest.TestCase):
    def test_bare_hex_lines(self):
        colors = parse_palette("#fff\n#1d4ed8\nabc\n")
        self.assertEqual([c.hex for c in colors],
                         ["#ffffff", "#1d4ed8", "#aabbcc"])

    def test_named_entries(self):
        colors = parse_palette("brand: #1d4ed8\nmuted #9ca3af\n")
        self.assertEqual([(c.name, c.hex) for c in colors],
                         [("brand", "#1d4ed8"), ("muted", "#9ca3af")])

    def test_comments_and_blanks_skipped(self):
        colors = parse_palette("\n# a comment\n// another\n#ff0000\n")
        self.assertEqual([c.hex for c in colors], ["#ff0000"])

    def test_invalid_line_raises(self):
        with self.assertRaises(InputError):
            parse_palette("#ff0000\nnot-a-color\n")


class JsonParsingTests(unittest.TestCase):
    def test_object(self):
        colors = parse_json_palette('{"brand": "#1D4ED8", "bg": "#fff"}')
        by_name = {c.name: c.hex for c in colors}
        self.assertEqual(by_name["brand"], "#1d4ed8")
        self.assertEqual(by_name["bg"], "#ffffff")

    def test_bad_json(self):
        with self.assertRaises(InputError):
            parse_json_palette("{oops")

    def test_non_dict(self):
        with self.assertRaises(InputError):
            parse_json_palette('["#ffffff"]')

    def test_bad_hex(self):
        with self.assertRaises(InputError):
            parse_json_palette('{"a": "banana"}')


class CheckPairsTests(unittest.TestCase):
    COLORS = [Color("ink", "#111111", 1), Color("muted", "#9ca3af", 2),
              Color("paper", "#ffffff", 3)]

    def test_all_pairs_checked(self):
        results = check_pairs(self.COLORS, None, 4.5)
        self.assertEqual(len(results), 3)  # 3 choose 2

    def test_identical_hex_skipped(self):
        colors = [Color("a", "#ffffff", 1), Color("b", "#FFFFFF", 2)]
        self.assertEqual(check_pairs(colors, None, 4.5), [])

    def test_bg_mode(self):
        results = check_pairs(self.COLORS, ["#ffffff"], 4.5)
        self.assertEqual(len(results), 2)
        by_fg = {r["fg"].name: r for r in results}
        self.assertTrue(by_fg["ink"]["passes"])
        self.assertFalse(by_fg["muted"]["passes"])

    def test_failing_pair_gets_fix(self):
        results = check_pairs(self.COLORS, ["#ffffff"], 4.5)
        failing = [r for r in results if not r["passes"]]
        self.assertEqual(len(failing), 1)
        self.assertIsNotNone(failing[0]["fix_hex"])
        self.assertGreaterEqual(failing[0]["fix_ratio"], 4.5)

    def test_report_json_shape(self):
        results = check_pairs(self.COLORS, ["#ffffff"], 4.5)

        class Args:
            level = "aa"
            large = False

        report = report_to_json(results, "AA normal text", "test", Args())
        self.assertEqual(report["tool"], "contrast-doctor")
        self.assertEqual(report["summary"]["pairs"], 2)
        self.assertEqual(report["summary"]["passed"] +
                         report["summary"]["failed"], 2)
        json.dumps(report)  # must serialize


class SanitizeVarTests(unittest.TestCase):
    def test_valid_var_kept(self):
        self.assertEqual(sanitize_var_name("--brand-700", 1), "--brand-700")

    def test_declaration_name_sanitized(self):
        name = sanitize_var_name("color@line8", 3)
        self.assertTrue(name.startswith("--"))
        self.assertNotIn("@", name)

    def test_fallback(self):
        self.assertEqual(sanitize_var_name("!!!", 7), "--contrast-doctor-fix-7")


class FixFileTests(unittest.TestCase):
    def test_writes_css(self):
        colors = [Color("muted", "#9ca3af", 1)]
        results = check_pairs(colors, ["#ffffff"], 4.5)
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "fixes.css")
            written = write_fix_file(path, results, "AA normal text")
            self.assertEqual(written, 1)
            with open(path, encoding="utf-8") as handle:
                text = handle.read()
        self.assertIn(":root {", text)
        self.assertIn("--muted:", text)
        self.assertNotIn("#9ca3af:", text)

    def test_no_failures_writes_empty_root(self):
        colors = [Color("ink", "#111111", 1)]
        results = check_pairs(colors, ["#ffffff"], 4.5)
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "fixes.css")
            written = write_fix_file(path, results, "AA normal text")
            self.assertEqual(written, 0)


class CliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.css_path = os.path.join(self.tmp.name, "theme.css")
        with open(self.css_path, "w", encoding="utf-8") as handle:
            handle.write(":root {\n  --ink: #111111;\n  --muted: #9ca3af;\n"
                         "  --paper: #ffffff;\n}\n")

    def run_main(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(argv)
        return code, out.getvalue(), err.getvalue()

    def test_check_fails_on_bad_contrast(self):
        code, out, _ = self.run_main(
            [self.css_path, "--bg", "#ffffff", "--check"])
        self.assertEqual(code, 1)
        self.assertIn("FAIL", out)
        self.assertIn("fix:", out)

    def test_check_passes_on_good_contrast(self):
        code, _, _ = self.run_main(
            [self.css_path, "--bg", "#ffffff", "--check", "--level", "aa",
             "--large"])
        # large-text AA is 3:1; #9ca3af on white is ~2.84, still fails.
        self.assertEqual(code, 1)

    def test_no_check_exits_zero_with_failures(self):
        code, out, _ = self.run_main([self.css_path, "--bg", "#ffffff"])
        self.assertEqual(code, 0)
        self.assertIn("FAIL", out)

    def test_missing_file_is_exit_2(self):
        code, _, err = self.run_main(["/nope/missing.css", "--check"])
        self.assertEqual(code, 2)
        self.assertIn("error", err)

    def test_bad_bg_is_exit_2(self):
        code, _, err = self.run_main(
            [self.css_path, "--bg", "banana", "--check"])
        self.assertEqual(code, 2)
        self.assertIn("error", err)

    def test_bad_min_ratio_is_exit_2(self):
        with self.assertRaises(SystemExit) as ctx:
            main([self.css_path, "--min-ratio", "99"])
        self.assertEqual(ctx.exception.code, 2)

    def test_json_output_parses(self):
        code, out, _ = self.run_main(
            [self.css_path, "--bg", "#ffffff", "--json"])
        self.assertEqual(code, 0)
        report = json.loads(out)
        self.assertEqual(report["tool"], "contrast-doctor")
        self.assertEqual(report["threshold"], 4.5)

    def test_fix_out_file(self):
        fix_path = os.path.join(self.tmp.name, "fixes.css")
        code, _, _ = self.run_main(
            [self.css_path, "--bg", "#ffffff", "--fix-out", fix_path])
        self.assertEqual(code, 0)
        with open(fix_path, encoding="utf-8") as handle:
            text = handle.read()
        self.assertIn("--muted:", text)

    def test_json_palette_input(self):
        json_path = os.path.join(self.tmp.name, "p.json")
        with open(json_path, "w", encoding="utf-8") as handle:
            handle.write('{"ink": "#111111", "paper": "#ffffff"}')
        code, out, _ = self.run_main([json_path, "--check"])
        self.assertEqual(code, 0)
        self.assertIn("1 pairs: 1 passed, 0 failed", out)

    def test_detect_format(self):
        self.assertEqual(detect_format("a.css"), "css")
        self.assertEqual(detect_format("a.json"), "json")
        self.assertEqual(detect_format("a.txt"), "palette")


class NoEmDashTests(unittest.TestCase):
    def test_no_em_dashes_in_repo_text(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        offenders = []
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames
                           if d not in ("__pycache__", ".pytest_cache",
                                        ".git")]
            for filename in filenames:
                if not filename.endswith((".py", ".md", ".toml", ".css",
                                           ".txt", ".json")):
                    continue
                path = os.path.join(dirpath, filename)
                with open(path, encoding="utf-8") as handle:
                    if "\u2014" in handle.read():
                        offenders.append(path)
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()


class OklchTests(unittest.TestCase):
    def test_known_anchors(self):
        self.assertEqual(_resolve_oklch("oklch(1 0 0)"), "#ffffff")
        self.assertEqual(_resolve_oklch("oklch(0 0 0)"), "#000000")
        # CSS Color 4: pure red is oklch(62.8% 0.2577 29.23)
        self.assertEqual(_resolve_oklch("oklch(62.8% 0.2577 29.23)"), "#ff0000")

    def test_percent_lightness_equals_zero_one_form(self):
        self.assertEqual(
            _resolve_oklch("oklch(62.8% 0.2577 29.23)"),
            _resolve_oklch("oklch(0.628 0.2577 29.23)"),
        )

    def test_hue_wraps(self):
        self.assertEqual(
            _resolve_oklch("oklch(0.628 0.2577 389.23)"),
            _resolve_oklch("oklch(0.628 0.2577 29.23)"),
        )

    def test_out_of_gamut_clamps(self):
        # chroma beyond sRGB gamut clamps instead of being dropped
        out = _resolve_oklch("oklch(0.5 0.4 140)")
        self.assertRegex(out, r"^#[0-9a-f]{6}$")

    def test_alpha_and_garbage_are_skipped(self):
        self.assertIsNone(_resolve_oklch("oklch(0.5 0.1 200 / 0.5)"))
        self.assertIsNone(_resolve_oklch("oklch(0.5 0.1)"))
        self.assertIsNone(_resolve_oklch("oklch(high none low)"))

    def test_parse_css_picks_up_oklch_tokens(self):
        colors = parse_css(":root { --accent: oklch(62.8% 0.2577 29.23); }")
        self.assertEqual([(c.name, c.hex) for c in colors], [("--accent", "#ff0000")])


class ColorMixTests(unittest.TestCase):
    def test_explicit_weights(self):
        self.assertEqual(
            _resolve_color_mix("color-mix(in srgb, #ff0000 25%, #0000ff)"),
            "#4000bf",
        )
        self.assertEqual(
            _resolve_color_mix("color-mix(in srgb, #ff0000 25%, #0000ff 75%)"),
            "#4000bf",
        )

    def test_default_is_fifty_fifty(self):
        self.assertEqual(_resolve_color_mix("color-mix(in srgb, red, blue)"), "#800080")

    def test_single_weight_takes_remainder(self):
        self.assertEqual(
            _resolve_color_mix("color-mix(in srgb, red 20%, blue)"), "#3300cc"
        )

    def test_mixes_resolve_their_own_colors(self):
        self.assertEqual(
            _resolve_color_mix("color-mix(in srgb, oklch(1 0 0) 50%, black)"),
            "#808080",
        )

    def test_non_srgb_and_broken_forms_are_skipped(self):
        self.assertIsNone(_resolve_color_mix("color-mix(in oklab, red, blue)"))
        self.assertIsNone(_resolve_color_mix("color-mix(in srgb, red)"))
        self.assertIsNone(_resolve_color_mix("color-mix(in srgb, var(--x), blue)"))
        # CSS normalizes weights that sum over 100 instead of rejecting them
        self.assertEqual(_resolve_color_mix("color-mix(in srgb, red 120%, blue)"), "#ff0000")

    def test_parse_css_picks_up_mix_in_background(self):
        colors = parse_css("a { background: color-mix(in srgb, #ff0000 25%, #0000ff); }")
        self.assertEqual([c.hex for c in colors], ["#4000bf"])
