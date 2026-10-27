"""Make a small copy of a PDF printed by Chrome, light enough to attach through the Gmail connector.

Chrome embeds its fonts, which is most of a 200 KB report. This swaps them for the standard
PDF fonts that every reader has (Helvetica, Courier), writes each word as one piece of text
instead of one glyph at a time, drops the accessibility tags and compresses the rest. The
layout, tables and charts stay as they are. The reports use Liberation Sans and Liberation
Mono, which have the same letter widths as Helvetica and Courier, so nothing moves.

Usage:
    uv run python analysis/slim_pdf.py IN.pdf OUT.pdf

The evening run makes these for every report (analysis/watchlist.py, light_copies).
"""

from __future__ import annotations

import re
import sys
import unicodedata
from decimal import Decimal
from pathlib import Path

import pikepdf
from pikepdf import Dictionary, Name, Operator, String

TAGS = {"BDC", "BMC", "EMC", "MP", "DP"}


def to_unicode(font: pikepdf.Object) -> dict[int, str]:
    """Glyph code -> text, from the font's ToUnicode map."""
    out: dict[int, str] = {}
    if "/ToUnicode" not in font:
        return out
    s = font.ToUnicode.read_bytes().decode("latin-1")
    hexes = r"<([0-9A-Fa-f]+)>"
    for block in re.findall(r"beginbfchar(.*?)endbfchar", s, re.S):
        for a, b in re.findall(hexes + r"\s*" + hexes, block):
            out[int(a, 16)] = bytes.fromhex(b).decode("utf-16-be", "replace")
    for block in re.findall(r"beginbfrange(.*?)endbfrange", s, re.S):
        for a, b, c in re.findall(
            hexes + r"\s*" + hexes + r"\s*(<[0-9A-Fa-f]+>|\[[^\]]*\])", block
        ):
            lo, hi = int(a, 16), int(b, 16)
            if c.startswith("<"):
                for i in range(hi - lo + 1):
                    out[lo + i] = chr(int(c[1:-1], 16) + i)
            else:
                for i, h in enumerate(re.findall(hexes, c)):
                    out[lo + i] = bytes.fromhex(h).decode("utf-16-be", "replace")
    return out


def widths(font: pikepdf.Object) -> dict[int, float]:
    """Glyph code -> advance width, in thousandths of the font size."""
    out: dict[int, float] = {}
    if "/DescendantFonts" not in font:
        return out
    w = list(font.DescendantFonts[0].get("/W", []))
    i = 0
    while i < len(w):
        first = int(w[i])
        if isinstance(w[i + 1], pikepdf.Array):
            for j, x in enumerate(w[i + 1]):
                out[first + j] = float(x)
            i += 2
        else:
            for c in range(first, int(w[i + 1]) + 1):
                out[c] = float(w[i + 2])
            i += 3
    return out


def standard_font(base: str) -> str:
    family = "Courier" if "Mono" in base else "Helvetica"
    return f"{family}-Bold" if "Bold" in base else family


def text(codes: bytes, glyphs: dict[int, str]) -> str:
    t = "".join(glyphs.get(c, "?") for c in split(codes))
    t = unicodedata.normalize("NFKC", t)  # ligatures and non-breaking spaces
    return t.replace("\u2212", "-").replace("\u2011", "-")


def split(codes: bytes) -> list[int]:
    return [int.from_bytes(codes[i : i + 2], "big") for i in range(0, len(codes), 2)]


def short(x, places: int = 3):
    if isinstance(x, (int, float, Decimal)):
        r = round(float(x), places)
        return int(r) if r == int(r) else r
    return x


PATHS = {"m", "l", "c", "v", "y", "re"}


def rewrite(ops, fonts: dict[str, tuple[dict[int, str], dict[int, float]]]):
    """Drop the tags, re-encode the text and join Chrome's one-glyph-at-a-time text into lines.

    Chrome places every glyph with its own Td. Glyphs that sit exactly where the previous
    one ends (and words exactly one space apart) are written as one string; anything else
    starts a new string at its own position, so tables and alignment are kept.
    """
    out = []
    glyphs: dict[int, str] = {}
    advance: dict[int, float] = {}
    size = 0.0
    space = 0.0
    at = (0.0, 0.0)  # where the next glyph goes, relative to the last Tm
    run: list[str] = []
    start = (0.0, 0.0)  # where the run starts
    end = (0.0, 0.0)  # where the run ends
    placed = (0.0, 0.0)  # where the last run written starts
    gap = False  # a space was seen since the last glyph

    def flush():
        nonlocal run, placed
        if run:
            dx, dy = round(start[0] - placed[0], 3), round(start[1] - placed[1], 3)
            if dx or dy:
                out.append(([short(dx), short(dy)], Operator("Td")))
            out.append(([String("".join(run).encode("cp1252", "replace"))], Operator("Tj")))
            placed = start
        run = []

    for operands, op in ops:
        name = str(op)
        if name in TAGS:
            continue
        if name == "Td":
            at = (at[0] + float(operands[0]), at[1] + float(operands[1]))
            continue
        if name == "Tj":
            codes = split(bytes(operands[0]))
            t = text(bytes(operands[0]), glyphs)
            if t.strip() == "":
                gap = True
                continue
            width = sum(advance.get(c, 0.0) for c in codes) * size / 1000
            expected = end[0] + (space if gap else 0.0)
            if (
                run and abs(at[1] - end[1]) < 0.01 and abs(at[0] - expected) < 0.1 * size
            ):  # ignores kerning
                run.append(" " + t if gap else t)
            else:
                flush()
                run, start = [t], at
            end = (at[0] + width, at[1])
            gap = False
            continue
        flush()
        gap = False
        if name == "Tf":
            glyphs, advance = fonts.get(str(operands[0]), ({}, {}))
            size = float(operands[1])
            codes = [c for c, g in glyphs.items() if g == " "]
            space = advance.get(codes[0], 278.0) * size / 1000 if codes else 0.278 * size
        if name in ("Tm", "BT"):
            at = placed = end = (0.0, 0.0)
        if name == "TJ":
            operands = [
                pikepdf.Array(
                    String(text(bytes(x), glyphs).encode("cp1252", "replace"))
                    if isinstance(x, String)
                    else x
                    for x in operands[0]
                )
            ]
        places = 1 if name in PATHS else 3
        out.append(([short(x, places) for x in operands], op))
    flush()
    return out


def slim(src: Path, dst: Path) -> None:
    pdf = pikepdf.open(src)
    for key in ("/StructTreeRoot", "/MarkInfo", "/Metadata", "/Outlines"):
        if key in pdf.Root:
            del pdf.Root[key]
    standard: dict[str, pikepdf.Object] = {}
    for page in pdf.pages:
        fonts = page.Resources.get("/Font", Dictionary())
        maps = {}
        for name in list(fonts.keys()):
            font = fonts[name]
            maps[name] = (to_unicode(font), widths(font))
            base = standard_font(str(font.BaseFont))
            if base not in standard:
                standard[base] = pdf.make_indirect(
                    Dictionary(
                        Type=Name.Font,
                        Subtype=Name.Type1,
                        BaseFont=Name("/" + base),
                        Encoding=Name.WinAnsiEncoding,
                    )
                )
            fonts[name] = standard[base]
        ops = rewrite(pikepdf.parse_content_stream(page), maps)
        page.Contents = pdf.make_stream(pikepdf.unparse_content_stream(ops))
        if "/StructParents" in page.obj:
            del page.obj["/StructParents"]
    pdf.remove_unreferenced_resources()
    pdf.save(
        dst,
        compress_streams=True,
        recompress_flate=True,
        object_stream_mode=pikepdf.ObjectStreamMode.generate,
        deterministic_id=True,
    )


if __name__ == "__main__":
    slim(Path(sys.argv[1]), Path(sys.argv[2]))
