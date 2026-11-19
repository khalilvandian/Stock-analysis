"""Draws the "Inside the database, in UML" section of docs/pipeline.html (UML 2.5
diagrams and their notes). Rerun after a change: python docs/pipeline_uml.py docs/pipeline.html"""

# ruff: noqa: E501  (the SVG and the HTML notes are kept on one line each)
import re
import sys
from html import escape
from pathlib import Path

PAGE = Path(sys.argv[1])


class D:
    def __init__(self, pid, w, h, kind, name, aria):
        self.p, self.w, self.h, self.o = pid, w, h, []
        self.add(f'<svg viewBox="0 0 {w} {h}" role="img" aria-label="{escape(aria)}">')
        self.add(
            f'<defs><marker id="{pid}-a" viewBox="0 0 10 10" refX="9.5" refY="5" '
            'markerWidth="9" markerHeight="9" orient="auto-start-reverse" markerUnits="userSpaceOnUse">'
            '<path class="u-ah" d="M0,0 L10,5 L0,10"/></marker></defs>'
        )
        self.kind, self.name = kind, name

    def add(self, s):
        self.o.append(s)

    def t(self, x, y, s, cls, anchor=None, extra=""):
        a = f' text-anchor="{anchor}"' if anchor else ""
        self.add(f'<text class="{cls}" x="{x:g}" y="{y:g}"{a}{extra}>{escape(s)}</text>')

    def frame(self, x, y, w, h):
        self.add(f'<rect class="u-frame" x="{x}" y="{y}" width="{w}" height="{h}"/>')
        label = f"{self.kind}  {self.name}"
        tw = 18 + 7 * len(label)
        self.add(f'<path class="u-frame-tag" d="M{x},{y} h{tw} v14 l-9,10 H{x} z"/>')
        self.t(x + 8, y + 16, self.kind, "u-tagk")
        self.t(x + 8 + 7.5 * (len(self.kind) + 2), y + 16, self.name, "u-tag")

    def lines(self, x, y, w, h, lines, cls="u-act", first_cls=None):
        n = len(lines)
        y0 = y + h / 2 - (n - 1) * 7.5 + 4
        for i, s in enumerate(lines):
            c = first_cls if (first_cls and i == 0) else cls
            if isinstance(s, tuple):
                s, c = s
            self.t(x + w / 2, y0 + i * 15, s, c, "middle")

    def action(self, x, y, w, h, lines, call=False):
        self.add(f'<rect class="u-node" x="{x}" y="{y}" width="{w}" height="{h}" rx="12"/>')
        self.lines(x, y, w, h, lines)
        if call:  # rake: call behaviour action
            rx, ry = x + w - 14, y + h - 14
            self.add(f'<path class="u-rake" d="M{rx},{ry} v10 M{rx - 5},{ry + 10} v-5 h10 v5"/>')
        return box(x, y, w, h)

    def obj(self, x, y, w, h, lines, store=False):
        self.add(f'<rect class="u-node" x="{x}" y="{y}" width="{w}" height="{h}"/>')
        ls = ([("«datastore»", "u-kw")] if store else []) + list(lines)
        self.lines(x, y, w, h, ls, "u-obj")
        return box(x, y, w, h)

    def state(self, x, y, w, h, name):
        self.add(f'<rect class="u-node" x="{x}" y="{y}" width="{w}" height="{h}" rx="10"/>')
        self.lines(x, y, w, h, [name])
        return box(x, y, w, h)

    def diamond(self, cx, cy, r=13):
        self.add(
            f'<path class="u-node" d="M{cx},{cy - r} L{cx + r},{cy} L{cx},{cy + r} '
            f'L{cx - r},{cy} z"/>'
        )

    def initial(self, cx, cy):
        self.add(f'<circle class="u-solid" cx="{cx}" cy="{cy}" r="8"/>')

    def final(self, cx, cy):
        self.add(f'<circle class="u-node" cx="{cx}" cy="{cy}" r="11"/>')
        self.add(f'<circle class="u-solid" cx="{cx}" cy="{cy}" r="6.5"/>')

    def flow_final(self, cx, cy):
        r = 9
        d = r * 0.7071
        self.add(f'<circle class="u-node" cx="{cx}" cy="{cy}" r="{r}"/>')
        self.add(
            f'<path class="u-line" d="M{cx - d:.1f},{cy - d:.1f} L{cx + d:.1f},{cy + d:.1f} '
            f'M{cx - d:.1f},{cy + d:.1f} L{cx + d:.1f},{cy - d:.1f}"/>'
        )

    def exp_node(self, x, y, vertical):
        if vertical:
            self.add(f'<rect class="u-node" x="{x}" y="{y}" width="12" height="30"/>')
            self.add(f'<path class="u-line" d="M{x},{y + 10} h12 M{x},{y + 20} h12"/>')
        else:
            self.add(f'<rect class="u-node" x="{x}" y="{y}" width="30" height="12"/>')
            self.add(f'<path class="u-line" d="M{x + 10},{y} v12 M{x + 20},{y} v12"/>')

    def edge(self, pts, dashed=False, arrow=True):
        d = "M" + " L".join(f"{x:g},{y:g}" for x, y in pts)
        cls = "u-line dash" if dashed else "u-line"
        m = f' marker-end="url(#{self.p}-a)"' if arrow else ""
        self.add(f'<path class="{cls}" d="{d}"{m}/>')

    def g(self, x, y, s, anchor="start"):
        self.t(x, y, s, "u-g", anchor)

    def note(self, x, y, w, lines, to=None, frm=None):
        h = 12 + 15 * len(lines)
        f = 9
        self.add(
            f'<path class="u-note" d="M{x},{y} H{x + w - f} L{x + w},{y + f} V{y + h} H{x} z '
            f'M{x + w - f},{y} V{y + f} H{x + w}"/>'
        )
        for i, s in enumerate(lines):
            cls = "u-n"
            if isinstance(s, tuple):
                s, kind = s
                cls = {"mono": "u-nm"}[kind]
            self.t(x + 8, y + 18 + i * 15, s, cls)
        if to:
            sx, sy = frm or (x, y + h / 2)
            self.add(f'<path class="u-line dash" d="M{sx:g},{sy:g} L{to[0]:g},{to[1]:g}"/>')
        return box(x, y, w, h)

    def package(self, x, y, w, h, name):
        tw = 22 + 7.5 * len(name)
        self.add(f'<path class="u-pkg" d="M{x},{y} h{tw} v18 H{x + w} V{y + h + 18} H{x} z"/>')
        self.add(f'<path class="u-line" d="M{x},{y + 18} h{tw}"/>')
        self.t(x + 10, y + 13.5, name, "u-pkgn")

    def cls(self, x, y, name, attrs, kw="table", w=None):
        aw = max([len(a) * 6.6 for a in attrs] + [len(name) * 7.3]) + 18
        w = w or round(aw)
        h = 38 + 14 * len(attrs) + 8
        self.add(f'<rect class="u-node" x="{x}" y="{y}" width="{w}" height="{h}"/>')
        self.t(x + w / 2, y + 14, f"«{kw}»", "u-kw", "middle")
        self.t(x + w / 2, y + 29, name, "u-cname", "middle")
        self.add(f'<path class="u-line" d="M{x},{y + 38} h{w}"/>')
        for i, a in enumerate(attrs):
            self.t(x + 8, y + 54 + i * 14, a, "u-attr")
        return box(x, y, w, h)

    def mult(self, x, y, s, anchor="start"):
        self.t(x, y, s, "u-mult", anchor)

    def lane_label(self, x, y, s):
        self.add(
            f'<text class="u-lane" x="{x}" y="{y}" text-anchor="middle" '
            f'transform="rotate(-90 {x} {y})">{escape(s)}</text>'
        )

    def svg(self):
        return "\n".join(self.o + ["</svg>"])


class box:
    def __init__(self, x, y, w, h):
        self.x, self.y, self.w, self.h = x, y, w, h
        self.l, self.r, self.t, self.b = x, x + w, y, y + h
        self.cx, self.cy = x + w / 2, y + h / 2


# ======================================================================= 1. nightly run
a = D(
    "u1",
    1300,
    620,
    "act",
    "Nightly ingest run",
    "UML activity diagram of the nightly ingest run in three partitions: the ingest job "
    "plans tasks, chooses its mode and fetches each due task into the raw layer; if new rows "
    "were stored the build rebuilds, in one transaction, only the companies with new raw "
    "data; coverage takes the snapshot that the next run reads to choose its mode, then the "
    "nightly analyses compute what the evening run reads.",
)
a.frame(10, 10, 1280, 600)
a.add('<rect class="u-part" x="24" y="46" width="1252" height="550"/>')
a.add('<path class="u-partl" d="M24,256 H1276 M24,486 H1276 M50,46 V596"/>')
a.lane_label(41, 151, "ingest job")
a.lane_label(41, 371, "db build · one transaction")
a.lane_label(41, 541, "coverage · analyses")

CY = 150
a.initial(74, CY)
pt = a.action(96, CY - 20, 100, 40, ["Plan tasks"])
cm = a.action(226, CY - 20, 110, 40, ["Choose mode"])
a.edge([(82, CY), (pt.l, CY)])
a.edge([(pt.r, CY), (cm.l, CY)])
a.note(
    60,
    58,
    140,
    ["one ops_task per", "source and company", ("ingest.toml", "mono")],
    to=(146, pt.t),
    frm=(146, 103),
)
a.note(
    212,
    58,
    150,
    ["backfill until each task", "has run once and 90% of", "values are present,", "then maintain"],
    to=(281, cm.t),
    frm=(281, 130),
)

# the expansion region: one iteration per due task
RX, RY, RW, RH = 372, 62, 688, 182
a.add(f'<rect class="u-region" x="{RX}" y="{RY}" width="{RW}" height="{RH}" rx="14"/>')
a.t(RX + 12, RY + 18, "«iterative»", "u-kw")
a.t(RX + 80, RY + 18, "each due task, in source order", "u-g")
a.exp_node(RX - 6, CY - 15, True)
a.edge([(cm.r, CY), (RX - 6, CY)])
fe = a.action(398, CY - 20, 124, 40, ["Fetch from source"])
a.edge([(RX + 6, CY), (fe.l, CY)])
a.diamond(562, CY)
a.edge([(fe.r, CY), (549, CY)])
st = a.action(616, CY - 20, 134, 40, ["Keep the payload,", "store new rows"])
a.edge([(575, CY), (st.l, CY)])
a.g(595, CY - 7, "[ok]", "middle")
rs = a.action(800, CY - 20, 120, 40, ["Reschedule task"])
a.edge([(st.r, CY), (rs.l, CY)])
a.edge([(562, CY - 13), (562, 104), (860, 104), (860, rs.t)])
a.g(572, 98, "[empty · error]")
a.flow_final(968, CY)
a.edge([(rs.r, CY), (959, CY)])
a.exp_node(668, RY + RH - 6, False)
a.edge([(683, st.b), (683, RY + RH - 6)])
a.note(
    386,
    176,
    262,
    [
        "SEC facts need the company's CIK, from",
        "the SEC ticker file; only the tags mapped",
        "in db_items.toml are stored",
    ],
    to=(460, fe.b),
    frm=(460, 176),
)
a.note(
    712,
    182,
    340,
    [
        "a source group stops at HTTP 429, its request",
        "budget or 10 failures in a row; its other tasks",
        "wait for the next run (see stm ops_task)",
    ],
    to=(860, rs.b),
    frm=(860, 182),
)

a.diamond(1110, CY)
a.edge([(RX + RW, CY), (1097, CY)])
a.g(1130, CY - 7, "[nothing new]")

# lane B, right to left
BY, BH = 328, 44
labels = [
    ["Build companies", "and index spells"],
    ["Pick companies", "with new raw data"],
    ["Build daily", "prices"],
    ["Build fundamentals"],
    ["Build trailing", "twelve months"],
    ["Run quality", "checks"],
    ["Commit build"],
]
centres = [1110 - 157 * i for i in range(7)]
bs = [
    a.action(c - 65, BY, 130, BH, lab, call=(i == 3))
    for i, (c, lab) in enumerate(zip(centres, labels, strict=True))
]
a.edge([(1110, CY + 13), (1110, BY)])
a.g(1118, 200, "[new rows]")
for i in range(6):
    a.edge([(bs[i].l, BY + BH / 2), (bs[i + 1].r, BY + BH / 2)])

raw = a.obj(579, 268, 120, 40, ["raw layer"], store=True)
a.edge([(683, RY + RH + 6), (683, raw.t)])
a.edge([(639, raw.b), (639, BY)])
a.note(
    724,
    268,
    270,
    ["standardise, fill, reconcile and derive:", "act Build fundamentals, below"],
    to=(bs[3].r - 6, BY),
    frm=(724, 290),
)
core = a.obj(108, 404, 120, 40, ["core layer"], store=True)
a.edge([(168, bs[6].b), (168, core.t)])
a.edge([(325, bs[5].b), (325, 424), (core.r, 424)])
a.note(
    420,
    398,
    400,
    [
        "warnings written to core_quality_issue:",
        "jump 10× · sources disagree · missing period",
        "balance sheet identity · implied shares jump",
        "price jump · short trading year",
    ],
    to=(372, bs[5].b),
    frm=(420, 420),
)

# lane C, left to right
CC = 541
a.diamond(70, CC, 12)
a.edge([(bs[6].l, BY + BH / 2), (70, BY + BH / 2), (70, CC - 12)])
a.edge([(1123, CY), (1250, CY), (1250, 582), (70, 582), (70, CC + 12)])
sn = a.action(104, CC - 20, 128, 40, ["Take coverage", "snapshot"])
a.edge([(82, CC), (sn.l, CC)])
a.edge([(168, core.b), (168, sn.t)])
out = a.obj(270, CC - 20, 150, 40, ["out_coverage_snapshot"], store=True)
a.edge([(sn.r, CC), (out.l, CC)])
na = a.action(460, CC - 20, 150, 40, ["Nightly analyses", ("nightly.run", "u-objm")])
a.edge([(out.r, CC), (na.l, CC)])
rr = a.action(650, CC - 20, 120, 40, ["Record the run"])
a.edge([(na.r, CC), (rr.l, CC)])
a.final(810, CC)
a.edge([(rr.r, CC), (799, CC)])
a.note(
    850,
    496,
    380,
    [
        "nightly analyses: the screener, each watch-list",
        "stock's and the market's numbers (out_*), read",
        "by the evening run; ops_run keeps each run's summary",
    ],
    to=(rr.r, 525),
    frm=(850, 525),
)
# object flow: the snapshot is read by the next run's Choose mode
hy = BY + BH / 2
a.add(
    f'<path class="u-line" d="M345,{out.t} V494 H403 V{hy + 7} A7,7 0 0 1 403,{hy - 7} '
    f'V262 H281 V{cm.b}" marker-end="url(#u1-a)"/>'
)
a.g(290, 276, "read by the next run")
SVG1 = a.svg()

# ======================================================================= 2. build fundamentals
b = D(
    "u2",
    1300,
    362,
    "act",
    "Build fundamentals",
    "UML activity diagram of building core_fundamental in four partitions: standardise maps "
    "tags to items and classifies periods; fill derives second and third quarters from "
    "year-to-date values; reconcile chooses one value per key by source rank; derive adds "
    "fourth quarters and sums and applies split factors.",
)
b.frame(70, 10, 1163, 342)
cols = [
    (140, 398, "standardise"),
    (398, 522, "fill"),
    (522, 758, "reconcile"),
    (758, 1172, "derive"),
]
b.add('<rect class="u-part" x="140" y="46" width="1032" height="294"/>')
for x0, x1, name in cols:
    if x0 > 140:
        b.add(f'<path class="u-partl" d="M{x0},46 V340"/>')
    b.t((x0 + x1) / 2, 63, name, "u-lane", "middle")
b.add('<path class="u-partl" d="M140,72 H1172"/>')

MY, MH = 140, 44
mid = MY + MH / 2
params = [
    "raw_sec_fact",
    "raw_sec_xbrl_fact",
    "raw_yahoo_statement",
    "raw_project_history",
    "core_item_tag",
]
for i, p in enumerate(params):
    y = 86 + i * 44
    b.add(f'<rect class="u-node" x="4" y="{y}" width="132" height="30"/>')
    b.t(70, y + 19, p, "u-objm", "middle")
    b.edge([(136, y + 15), (146, y + 15), (146, mid), (150, mid)], arrow=(i == 1))
s1 = b.action(150, MY, 100, MH, ["Map tags", "to items"])
s2 = b.action(274, MY, 110, MH, ["Classify", "periods"])
f1 = b.action(410, MY, 102, MH, ["Q2, Q3 from", "year to date"])
o1 = b.obj(532, MY, 92, MH, ["candidates", ("[standardised]", "u-st")])
r1 = b.action(644, MY, 104, MH, ["Choose one", "per key"])
o2 = b.obj(768, MY, 72, MH, ["values", ("[chosen]", "u-st")])
d1 = b.action(860, MY, 92, MH, ["Derive Q4"])
d2 = b.action(970, MY, 92, MH, ["Derive sums"])
d3 = b.action(1080, MY, 86, MH, ["Apply split", "factors"])
seq = [s1, s2, f1, o1, r1, o2, d1, d2, d3]
for p, q in zip(seq, seq[1:], strict=False):
    b.edge([(p.r, mid), (q.l, mid)])
b.add(f'<rect class="u-node" x="1176" y="{mid - 15}" width="114" height="30"/>')
b.t(1233, mid + 4, "core_fundamental", "u-objm", "middle")
b.edge([(d3.r, mid), (1176, mid)])

b.note(
    150,
    222,
    240,
    [
        "17 items, tags tried by priority",
        "units and sign from db_items.toml",
        "Q 80–120 days, FY 350–380 days",
        "a quarter placed by days since year end,",
        "dated at its fiscal-calendar month end;",
        "more than a month off its slot: dropped",
        "helpers: parts of a formula, not stored",
    ],
    to=(s2.cx, s2.b),
    frm=(s2.cx, 222),
)
b.note(
    406, 222, 110, ["SEC only", "Q2 = H1 − Q1", "Q3 = 9M − H1"], to=(f1.cx, f1.b), frm=(f1.cx, 222)
)
b.note(
    532,
    222,
    220,
    [
        "key: company, item, period, filed",
        "SEC 1 › history 2 › Yahoo 3,",
        "then tag priority, latest fetch",
        "every filing date is kept",
    ],
    to=(r1.cx, r1.b),
    frm=(r1.cx, 222),
)
b.note(
    768,
    222,
    398,
    [
        "Q4 = FY − Q1 − Q2 − Q3 for SEC flows, not EPS",
        "EBITDA = operating income + D&A; total debt = short + long",
        "total liabilities = liabilities and equity − equity − temporary equity?",
        "a derived value never replaces one of a better rank; fallback",
        "items (total liabilities) keep the company's own figure",
        "split factor: splits after filing (shares, per share)",
    ],
    to=(d2.cx, d2.b),
    frm=(d2.cx, 222),
)
SVG2 = b.svg()

# ======================================================================= 3. class diagram
c = D(
    "u3",
    1300,
    850,
    "class",
    "Data layers",
    "UML class diagram of the database tables in four packages, raw, core, ops and out, "
    "with their key attributes, the foreign-key associations and their multiplicities.",
)
c.frame(10, 10, 1280, 830)
c.package(20, 46, 376, 640, "raw")
c.package(412, 46, 628, 590, "core")
c.package(1056, 46, 228, 360, "ops")
c.package(1056, 430, 228, 360, "out")

rf = c.cls(
    34,
    84,
    "raw_fetch",
    [
        "fetch_id : bigint {id}",
        "source : text",
        "request_key : text",
        "fetched_at : ts",
        "status : text",
        "payload_sha256 : text",
    ],
)
rph = c.cls(
    232,
    84,
    "raw_sec_xbrl_fact",
    [
        "cik : bigint",
        "accn : text",
        "concept : text",
        "axis : text",
        "member : text",
        "period_end : date",
        "value : float",
        "statement : text",
        "custom : bool",
    ],
)
rys = c.cls(
    232,
    286,
    "raw_yahoo_statement",
    [
        "symbol : text",
        "statement : text",
        "frequency : text",
        "period_end : date",
        "line_item : text",
        "value : float",
    ],
)
rsf = c.cls(
    34,
    270,
    "raw_sec_fact",
    [
        "cik : bigint",
        "taxonomy : text",
        "tag : text",
        "unit : text",
        "period_start : date",
        "period_end : date",
        "value : float",
        "fy : int",
        "fp : text",
        "form : text",
        "filed : date",
        "accn : text",
    ],
)
c.edge([(rf.r, 146), (rph.l, 146)], arrow=False)
c.mult(rf.r + 4, 160, "1")
c.mult(rph.l - 4, 140, "0..*", "end")
c.edge([(rf.r, 196), (212, 196), (212, 300), (rys.l, 300)], arrow=False)
c.mult(rf.r + 4, 190, "1")
c.mult(rys.l - 4, 294, "0..*", "end")
c.edge([(100, rf.b), (100, rsf.t)], arrow=False)
c.mult(106, rf.b + 14, "1")
c.mult(106, rsf.t - 6, "0..*")
c.note(
    34,
    504,
    156,
    [
        "also raw_project_history,",
        "raw_yahoo_price,",
        "raw_yahoo_earnings,",
        "raw_tv_constituent,",
        "raw_sec_ticker and",
        "raw_ecb_rate; each row",
        "points to one raw_fetch",
        "(1 to 0..*)",
    ],
)
rpl = c.cls(
    232,
    480,
    "raw_payload",
    [
        "fetch_id : bigint {id}",
        "media_type : text",
        "encoding : gzip",
        "size_bytes : bigint",
        "content : bytea",
    ],
    w=rys.w,
)
c.t(rpl.cx, rpl.b + 16, "each payload as it came", "u-kw", "middle")
# raw_fetch 1 -- 0..1 raw_payload, bridging the two lines it crosses
c.add(
    f'<path class="u-line" d="M{rf.r},206 H222 V293 A7,7 0 0 1 222,307 V423 '
    f'A7,7 0 0 1 222,437 V538 H{rpl.l}"/>'
)
c.mult(rf.r + 4, 220, "1")
c.mult(218, 532, "0..1", "end")

X1, X2, X3 = 428, 652, 866
ci = c.cls(
    X1,
    84,
    "core_item",
    ["item : text {id}", "label : text", "kind : flow | instant", "unit : text", "derive : text"],
)
cit = c.cls(
    X2,
    84,
    "core_item_tag",
    [
        "item : text {id}",
        "taxonomy : text {id}",
        "tag : text {id}",
        "priority : int",
        "scale : float",
    ],
)
cb = c.cls(
    X3,
    84,
    "core_build",
    [
        "build_id : bigint {id}",
        "started_at : ts",
        "max_fetch_id : bigint",
        "status : text",
        "summary : json",
    ],
)
cf = c.cls(
    X1,
    250,
    "core_fundamental",
    [
        "company_id : bigint {id}",
        "item : text {id}",
        "period_type : Q | FY | I {id}",
        "period_end : date {id}",
        "filed : date {id}",
        "value : float",
        "split_factor : float",
        "method : text",
        "source : text",
        "tag : text",
        "raw_table : text",
        "raw_id : bigint",
    ],
)
ct = c.cls(
    X2 + 14,
    250,
    "core_fundamental_ttm",
    [
        "company_id : bigint {id}",
        "item : text {id}",
        "period_end : date {id}",
        "filed : date {id}",
        "basis : fy | 4q | instant",
        "value : float",
        "value_adj : float",
    ],
)
cq = c.cls(
    X3 + 22,
    250,
    "core_quality_issue",
    [
        "issue_id : bigint {id}",
        "build_id : bigint",
        "company_id : bigint",
        "item : text",
        "at_date : date",
        "check_name : text",
        "severity : text",
        "detail : text",
    ],
)
cc = c.cls(
    X1,
    520,
    "core_company",
    ["company_id : bigint {id}", "symbol : text", "cik : bigint", "sector : text"],
)
cp = c.cls(
    X2 + 14,
    520,
    "core_price_daily",
    ["company_id : bigint {id}", "date : date {id}", "close : float", "adj_close : float"],
)
cim = c.cls(
    X3 + 22,
    520,
    "core_index_member",
    ["company_id {id}", "index_code {id}", "start_date {id}", "end_date : date"],
)
# associations
c.edge([(470, ci.b), (470, cf.t)], arrow=False)
c.mult(476, ci.b + 14, "1")
c.mult(476, cf.t - 6, "0..*")
c.edge([(ci.r, 140), (cit.l, 140)], arrow=False)
c.mult(ci.r + 4, 134, "1")
c.mult(cit.l - 4, 154, "0..*", "end")
c.edge([(cq.cx, cb.b), (cq.cx, cq.t)], arrow=False)
c.mult(cq.cx + 6, cb.b + 14, "1")
c.mult(cq.cx + 6, cq.t - 6, "0..*")
c.edge([(470, cc.t), (470, cf.b)], arrow=False)
c.mult(476, cc.t - 6, "1")
c.mult(476, cf.b + 14, "0..*")
c.edge([(cc.r, 570), (cp.l, 570)], arrow=False)
c.mult(cc.r + 4, 564, "1")
c.mult(cp.l - 4, 584, "0..*", "end")
c.edge([(520, cc.b), (520, 622), (cim.cx, 622), (cim.cx, cim.b)], arrow=False)
c.mult(526, cc.b + 14, "1")
c.mult(cim.cx + 6, cim.b + 14, "0..*")
c.edge([(cq.cx, cq.b), (cq.cx, 492), (560, 492), (560, cc.t)], arrow=False)
c.mult(cq.cx + 6, cq.b + 14, "0..*")
c.mult(566, cc.t - 6, "0..1")
# dependencies
c.edge([(ct.l, 330), (cf.r, 330)], dashed=True)
c.t((cf.r + ct.l) / 2, 322, "«derive»", "u-kw", "middle")
c.edge([(cf.l, 430), (rsf.r, 430)], dashed=True)
c.t(300, 422, "«trace»", "u-kw", "middle")
c.t(300, 446, "raw_table, raw_id", "u-mult", "middle")

ot = c.cls(
    1068,
    84,
    "ops_task",
    [
        "source : text {id}",
        "request_key : text {id}",
        "symbol : text",
        "active : bool",
        "status : text",
        "attempts : int",
        "next_due_at : ts",
        "last_fetch_id : bigint",
    ],
)
orun = c.cls(
    1068,
    270,
    "ops_run",
    [
        "run_id : bigint {id}",
        "mode : text",
        "status : text",
        "requests : int",
        "rows_stored : int",
        "build_id : bigint",
    ],
    w=ot.w,
)
c.edge([(orun.l, 330), (1048, 330), (1048, 150), (cb.r, 150)], arrow=False)
c.mult(orun.l - 4, 324, "0..*", "end")
c.mult(cb.r + 4, 144, "0..1")
oc = c.cls(
    1068,
    468,
    "out_coverage_snapshot",
    [
        "snapshot_date : date {id}",
        "universe : text",
        "companies : int",
        "companies_covered : int",
        "cells_required : int",
        "cells_present : int",
        "mode : text",
    ],
)
og = c.cls(
    1068,
    650,
    "out_coverage_gap",
    [
        "symbol : text {id}",
        "item : text {id}",
        "period : text {id}",
        "period_type : text {id}",
        "status : text",
        "reason : text",
        "snapshot_date : date",
    ],
    w=oc.w,
)
c.edge([(oc.cx, oc.b), (oc.cx, og.t)], arrow=False)
c.mult(oc.cx + 6, oc.b + 14, "1")
c.mult(oc.cx + 6, og.t - 6, "0..*")
c.edge([(1056, 720), (740, 720), (740, 654)], dashed=True)
c.t(900, 712, "«derive» from the core package", "u-kw", "middle")
c.note(
    34,
    716,
    350,
    ["{id} = primary key · multiplicities from foreign keys", ("ts = timestamp", "mono")],
)
SVG3 = c.svg()

# ======================================================================= 4. state machine
s = D(
    "u4",
    1300,
    390,
    "stm",
    "ops_task",
    "UML state machine of an ingest task: created pending, fetched when due into ok, empty or "
    "error with their retry times, fetched again when due; it becomes inactive when its "
    "company leaves the universe and resumes its last state when it rejoins.",
)
s.frame(10, 10, 1280, 370)
s.add('<rect class="u-node" x="90" y="40" width="920" height="290" rx="14"/>')
s.add('<path class="u-line" d="M90,62 H1010"/>')
s.t(550, 56, "active", "u-act", "middle")
SC = 204
s.initial(108, SC)
pe = s.state(130, SC - 20, 90, 40, "pending")
s.edge([(116, SC), (pe.l, SC)])
s.add(f'<circle class="u-solid" cx="330" cy="{SC}" r="5"/>')  # junction
s.edge([(pe.r, SC), (325, SC)])
s.g(273, SC - 8, "when(due) / fetch", "middle")
s.diamond(400, SC)
s.edge([(335, SC), (387, SC)])
s.add('<rect class="u-node" x="630" y="96" width="360" height="214" rx="12"/>')
s.add('<path class="u-line" d="M630,118 H990"/>')
s.t(810, 112, "fetched", "u-act", "middle")
ok = s.state(760, 130, 120, 36, "ok")
em = s.state(760, 186, 120, 36, "empty")
er = s.state(760, 246, 120, 36, "error")
s.edge([(400, SC - 13), (400, ok.cy), (ok.l, ok.cy)])
s.g(412, ok.cy - 7, "[ok] / due again after refresh_days")
s.edge([(413, SC), (em.l, SC)])
s.g(420, SC - 7, "[no data] / due again in 7 days")
s.edge([(400, SC + 13), (400, er.cy), (er.l, er.cy)])
s.g(412, er.cy - 7, "[failure] / attempts + 1, retry")
s.g(412, er.cy + 15, "in 6 h × 2^attempts, at most 24 h")
s.edge([(700, 96), (700, 80), (330, 80), (330, SC - 5)])
s.g(515, 74, "when(due) / fetch", "middle")
s.add('<circle class="u-node" cx="175" cy="290" r="11"/>')
s.t(175, 294, "H", "u-act", "middle")
ia = s.state(1120, 182, 130, 44, "inactive")
s.edge([(1010, 204), (ia.l, 204)])
s.g(1065, 197, "left universe", "middle")
s.edge([(1185, ia.b), (1185, 352), (175, 352), (175, 301)])
s.g(680, 368, "rejoined (resumes the last state)", "middle")
s.note(
    1040,
    40,
    240,
    [
        "status, attempts and next_due_at are",
        "columns of ops_task; HTTP 429 or a",
        "used budget stops the source group:",
        "the task keeps its state, stays due",
    ],
    to=(1010, 120),
    frm=(1040, 120),
)
SVG4 = s.svg()

# ======================================================================= 5. import a file
m = D(
    "u6",
    1300,
    232,
    "act",
    "Import a file",
    "UML activity diagram of db import: a file downloaded by hand is read; for each payload in "
    "it, a new one is kept and parsed into the raw tables, one seen before only gets its kept "
    "copy; then the tasks it covered count as fetched, so the job does not download it again.",
)
m.frame(10, 10, 1280, 212)
IY = 128
m.initial(40, IY)
rd = m.action(64, IY - 22, 132, 44, ["Read the file", ("inbox/<kind>/", "u-objm")])
m.edge([(48, IY), (rd.l, IY)])
GX, GW = 232, 640
m.add(f'<rect class="u-region" x="{GX}" y="52" width="{GW}" height="158" rx="14"/>')
m.t(GX + 12, 70, "«iterative»", "u-kw")
m.t(GX + 80, 70, "each payload in it: a company's facts, a quarter's data set", "u-g")
m.exp_node(GX - 6, IY - 15, True)
m.edge([(rd.r, IY), (GX - 6, IY)])
m.diamond(300, IY)
m.edge([(GX + 6, IY), (287, IY)])
kp = m.action(344, IY - 22, 116, 44, ["Keep the", "payload"])
m.edge([(313, IY), (kp.l, IY)])
m.g(318, IY - 8, "[new]")
ps = m.action(488, IY - 22, 116, 44, ["Parse into", "raw tables"])
m.edge([(kp.r, IY), (ps.l, IY)])
m.diamond(640, IY)
m.edge([(ps.r, IY), (627, IY)])
m.edge([(300, IY + 13), (300, 188), (640, 188), (640, IY + 13)])
m.g(310, 182, "[seen before] / keep its copy only")
mk = m.action(676, IY - 22, 130, 44, ["Mark its tasks", "fetched"])
m.edge([(653, IY), (mk.l, IY)])
m.flow_final(840, IY)
m.edge([(mk.r, IY), (831, IY)])
m.final(910, IY)
m.edge([(GX + GW, IY), (899, IY)])
m.note(
    946,
    52,
    330,
    [
        "db import FILE --target server: from this PC",
        "straight into the Azure database",
        "the same parsers as the API sources;",
        "due again after the source's refresh interval,",
        "as if fetched on the file's date: the job",
        "never downloads what was imported;",
        "db push replays the PC's kept payloads",
        ("sec_companyfacts · sec_fsds", "mono"),
    ],
    to=(mk.cx, mk.t),
    frm=(946, 90),
)
SVG6 = m.svg()

# ======================================================================= 0. sources and their data
src = D(
    "u10",
    1300,
    760,
    "class",
    "Sources and the data they deliver",
    "UML diagram of each source artifact with its format and contents, how it arrives, the "
    "loader that reads it and the raw table it is stored in; every raw table feeds the build "
    "of the core layer, and every payload is kept as received.",
)
src.frame(10, 10, 1280, 740)
for x, s in (
    (274, "what arrives · format · how"),
    (690, "loader"),
    (965, "raw table"),
    (1190, "then"),
):
    src.t(x, 62, s, "u-lane", "middle")
src.add('<path class="u-partl" d="M24,72 H1276"/>')
ROWS = [
    (
        "SEC company facts",
        "JSON per company: every reported fact, by tag, unit and period",
        "API · the nightly job, one company a request",
    ),
    (
        "SEC companyfacts.zip",
        "ZIP of the same JSON files, every company at once",
        "bulk file you download → inbox/sec_companyfacts/ · db import",
    ),
    (
        "SEC Financial Statement Data Sets",
        "ZIP a quarter of tab-separated text: filings, numbers, statement lines",
        "bulk file you download → inbox/sec_fsds/ · db import",
    ),
    (
        "SEC full filing (XBRL)",
        "XML of one 10-K or 10-Q: instance, schema, linkbases",
        "API through edgartools · values still missing per share class",
    ),
    ("SEC company tickers", "JSON: every ticker with its CIK", "API · the nightly job"),
    (
        "Yahoo daily prices",
        "table a symbol: open, high, low, close, volume, dividends, splits",
        "yfinance · the nightly job · companies and the market report's instruments",
    ),
    (
        "Yahoo statements",
        "tables a company: income, balance sheet, cash flow, annual and quarterly",
        "yfinance · Yahoo keeps about four years",
    ),
    (
        "Yahoo earnings dates",
        "table: report dates with reported and expected EPS",
        "yfinance · the nightly job",
    ),
    (
        "TradingView screener",
        "JSON: listings with index membership, sector, industry and the screener's fields",
        "two scans a night: the index, and the watch list's other symbols",
    ),
    ("ECB reference rates", "CSV: daily euro exchange rates", "API · the nightly job"),
    (
        "history.csv (retired)",
        "CSV: the project's own SEC-based yearly history, from before the database",
        "loaded once; the file and its loader are gone, the rows stay",
    ),
]
RY0, RS, RHT = 82, 54, 46
arts = []
for i, (name, what, how) in enumerate(ROWS):
    y = RY0 + i * RS
    arts.append(
        src.obj(24, y, 500, RHT, [(f"«artifact» {name}", "u-act"), (what, "u-n"), (how, "u-nm")])
    )
# loaders and tables: (first row, last row, loader lines, table)
GROUPS = [
    (0, 1, ["Parse company facts", ("sec.load_companyfacts", "u-objm")], "raw_sec_fact"),
    (2, 2, ["Read a quarter", ("files.import_fsds", "u-objm")], None),
    (3, 3, ["Read a filing", ("xbrl.load_filing", "u-objm")], None),
    (4, 4, ["Read tickers", ("sec.load_tickers", "u-objm")], "raw_sec_ticker"),
    (5, 5, ["Load prices", ("yahoo.load_prices", "u-objm")], "raw_yahoo_price"),
    (6, 6, ["Load statements", ("yahoo.load_statements", "u-objm")], "raw_yahoo_statement"),
    (7, 7, ["Load earnings", ("yahoo.load_earnings", "u-objm")], "raw_yahoo_earnings"),
    (8, 8, ["Load snapshots", ("market.load_*", "u-objm")], "raw_tv_constituent"),
    (9, 9, ["Load rates", ("market.load_rates", "u-objm")], "raw_ecb_rate"),
    (10, 10, ["No loader now", ("kept as loaded", "u-st")], "raw_project_history"),
]
tables = []
for first, last, lines, table in GROUPS:
    y0, y1 = RY0 + first * RS, RY0 + last * RS + RHT
    ld = src.action(590, y0, 200, y1 - y0, lines)
    for i in range(first, last + 1):
        cy = arts[i].cy
        src.edge([(arts[i].r, cy), (ld.l, cy)])
    if table:
        tb = src.obj(860, y0, 210, y1 - y0, [(table, "u-objm")], store=True)
        tables.append(tb)
        src.edge([(ld.r, (y0 + y1) / 2), (tb.l, (y0 + y1) / 2)])
    else:  # the data sets and the full filings share raw_sec_xbrl_fact
        if first == 2:
            xb = src.obj(860, y0, 210, RS + RHT, [("raw_sec_xbrl_fact", "u-objm")], store=True)
            tables.append(xb)
        src.edge([(ld.r, (y0 + y1) / 2), (860, (y0 + y1) / 2)])
BUS = 1100
src.add(f'<path class="u-line" d="M{BUS},{tables[0].cy} V{tables[-1].cy}"/>')
for tb in tables:
    src.edge([(tb.r, tb.cy), (BUS, tb.cy)], arrow=False)
src.add(f'<circle class="u-solid" cx="{BUS}" cy="{tables[4].cy}" r="4"/>')
bd = src.action(
    1130, tables[4].cy - 30, 140, 60, ["Build core", ("act Nightly run", "u-st")], call=True
)
src.edge([(BUS, tables[4].cy), (bd.l, tables[4].cy)])
co = src.obj(1130, tables[4].cy + 70, 140, 44, [("core layer", "u-obj")], store=True)
src.edge([(bd.cx, bd.b), (bd.cx, co.t)])
src.note(
    24,
    RY0 + len(ROWS) * RS + 6,
    1046,
    [
        "every payload is kept as received in raw_payload (gzip), with its raw_fetch row: source, request, time, fingerprint; a data-set quarter stays a file in inbox/",
        "the raw tables keep only new or changed rows, so a payload fetched again stores nothing; db reparse reads the kept payloads again after a mapping change",
    ],
)
SVG0 = src.svg()

# ======================================================================= 6. check a change on a sample
cs = D(
    "u11",
    1300,
    250,
    "act",
    "Check a change on a sample",
    "UML activity diagram of changing the extraction: re-read kept payloads if the parsing "
    "changed, build a sample of companies in a transaction, compare with the stored values and "
    "roll back; if the sample is right, write only those companies, otherwise change again.",
)
cs.frame(10, 10, 1280, 230)
SY = 120
cs.initial(40, SY)
ch = cs.action(
    64,
    SY - 30,
    200,
    60,
    ["Change the extraction", ("db_items.toml", "u-objm"), ("companies.toml · build.py", "u-objm")],
)
cs.edge([(48, SY), (ch.l, SY)])
cs.diamond(300, SY)
cs.edge([(ch.r, SY), (287, SY)])
rp = cs.action(340, 34, 150, 44, ["Re-read kept payloads", ("db reparse", "u-objm")])
cs.edge([(300, SY - 13), (300, rp.cy), (rp.l, rp.cy)])
cs.g(308, 98, "[parsing changed]")
cs.diamond(530, SY)
cs.edge([(rp.r, rp.cy), (530, rp.cy), (530, SY - 13)])
cs.edge([(313, SY), (517, SY)])
cs.g(380, SY + 18, "[mapping only]")
bsm = cs.action(
    566,
    SY - 26,
    170,
    52,
    ["Build the sample", "in one transaction", ("check-sample --symbols A,B", "u-objm")],
)
cs.edge([(543, SY), (bsm.l, SY)])
cmp_ = cs.action(764, SY - 22, 150, 44, ["Compare with the", "stored values"])
cs.edge([(bsm.r, SY), (cmp_.l, SY)])
rb = cs.action(942, SY - 22, 90, 44, ["Roll back"])
cs.edge([(cmp_.r, SY), (rb.l, SY)])
cs.diamond(1066, SY)
cs.edge([(rb.r, SY), (1053, SY)])
wr = cs.action(1100, SY - 26, 150, 52, ["Write the sample", ("build --symbols A,B", "u-objm")])
cs.edge([(1079, SY), (wr.l, SY)])
cs.g(1072, SY - 32, "[as expected]")
cs.final(1270, SY)
cs.edge([(wr.r, SY), (1259, SY)])
cs.edge([(1066, SY + 13), (1066, 214), (164, 214), (164, ch.b)])
cs.g(1074, 200, "[not as expected]")
cs.note(
    600,
    170,
    440,
    [
        "added · removed · changed per company; nothing is written",
        "the other companies keep their rows and take the change when",
        "their sources bring new data; build --full only when asked",
    ],
    to=(cmp_.cx, cmp_.b),
    frm=(cmp_.cx, 170),
)
SVG7 = cs.svg()

# ======================================================================= 7. PC to server
ps_ = D(
    "u12",
    1300,
    430,
    "act",
    "PC to server",
    "UML activity diagram in three partitions: on this PC bulk files are downloaded and "
    "imported, then db push sends every kept payload the server lacks through the same "
    "loaders; the server database stores it and marks the tasks fetched; the server job then "
    "fetches only its cheap daily sources and builds only the companies with new raw data.",
)
ps_.frame(10, 10, 1280, 410)
ps_.add('<rect class="u-part" x="24" y="46" width="1252" height="360"/>')
ps_.add('<path class="u-partl" d="M24,166 H1276 M24,286 H1276 M50,46 V406"/>')
ps_.lane_label(41, 106, "this PC")
ps_.lane_label(41, 226, "server database")
ps_.lane_label(41, 346, "server job")
PY1, PY2, PY3 = 106, 226, 346
ps_.initial(74, PY1)
dl = ps_.action(96, PY1 - 24, 150, 48, ["Download bulk files", ("inbox/<kind>/", "u-objm")])
ps_.edge([(82, PY1), (dl.l, PY1)])
im = ps_.action(276, PY1 - 24, 150, 48, ["Import and analyse", ("db import FILE", "u-objm")])
ps_.edge([(dl.r, PY1), (im.l, PY1)])
pu = ps_.action(
    456, PY1 - 24, 170, 48, ["Find what the server lacks", ("db push --target server", "u-objm")]
)
ps_.edge([(im.r, PY1), (pu.l, PY1)])
ps_.note(
    660,
    62,
    420,
    [
        "same source, request and fingerprint already there: skipped",
        "a data-set quarter is imported from its file in inbox/",
        ("sec_companyfacts · sec_xbrl · sec_fsds", "mono"),
    ],
    to=(pu.r, PY1 - 10),
    frm=(660, 84),
)
PX, PW = 140, 760
ps_.add(f'<rect class="u-region" x="{PX}" y="182" width="{PW}" height="92" rx="14"/>')
ps_.t(PX + 330, 198, "«iterative»", "u-kw")
ps_.t(PX + 398, 198, "each payload the server lacks, parsed on this PC", "u-g")
ps_.exp_node(235, 176, False)
ps_.edge([(541, pu.b), (541, 150), (250, 150), (250, 176)])
kp2 = ps_.action(
    170, PY2 - 18, 160, 44, ["Store the payload", ("raw_payload · raw_fetch", "u-objm")]
)
pl2 = ps_.action(370, PY2 - 18, 180, 44, ["Store new or changed rows", "with the source's loader"])
mk2 = ps_.action(590, PY2 - 18, 160, 44, ["Mark its tasks fetched", ("ops_task", "u-objm")])
ps_.edge([(250, 188), (250, kp2.t)])
ps_.edge([(kp2.r, kp2.cy), (pl2.l, pl2.cy)])
ps_.edge([(pl2.r, pl2.cy), (mk2.l, mk2.cy)])
ps_.flow_final(800, mk2.cy)
ps_.edge([(mk2.r, mk2.cy), (791, mk2.cy)])
rawsv = ps_.obj(960, PY2 - 22, 160, 44, [("raw layer", "u-obj")], store=True)
ps_.edge([(pl2.cx, pl2.b), (pl2.cx, 262), (1000, 262), (1000, rawsv.b)])
ps_.initial(74, PY3)
pt2 = ps_.action(96, PY3 - 22, 130, 44, ["Plan tasks"])
ps_.edge([(82, PY3), (pt2.l, PY3)])
fe2 = ps_.action(
    256,
    PY3 - 26,
    220,
    52,
    [
        "Fetch only the due tasks",
        ("TradingView · Yahoo · ECB daily;", "u-st"),
        ("SEC: what was not pushed", "u-st"),
    ],
)
ps_.edge([(pt2.r, PY3), (fe2.l, PY3)])
bu2 = ps_.action(506, PY3 - 22, 220, 44, ["Build the companies", "with new raw data"], call=True)
ps_.edge([(fe2.r, PY3), (bu2.l, PY3)])
cv2 = ps_.action(756, PY3 - 22, 150, 44, ["Take coverage", "snapshot"])
ps_.edge([(bu2.r, PY3), (cv2.l, PY3)])
ps_.final(940, PY3)
ps_.edge([(cv2.r, PY3), (929, PY3)])
ps_.edge([(1080, rawsv.b), (1080, 300), (616, 300), (616, bu2.t)])
ps_.g(1088, 296, "read by the build")
SVG8 = ps_.svg()

# ======================================================================= notation key
k = D("u5", 1300, 112, "", "", "Key to the UML symbols used in the diagrams.")
x = 24
row = 30
k.initial(x + 8, row)
k.t(x + 22, row + 4, "start", "u-n")
x += 70
k.final(x + 10, row)
k.t(x + 28, row + 4, "end", "u-n")
x += 66
k.flow_final(x + 9, row)
k.t(x + 26, row + 4, "end of one flow", "u-n")
x += 126
k.add(f'<rect class="u-node" x="{x}" y="{row - 12}" width="46" height="24" rx="10"/>')
k.t(x + 54, row + 4, "action", "u-n")
x += 104
k.diamond(x + 12, row, 11)
k.t(x + 30, row + 4, "decision / merge", "u-n")
x += 140
k.add(f'<rect class="u-node" x="{x}" y="{row - 12}" width="40" height="24"/>')
k.t(x + 48, row + 4, "object (data) · «datastore» table", "u-n")
x += 236
k.add(f'<rect class="u-region" x="{x}" y="{row - 12}" width="40" height="24" rx="8"/>')
k.t(x + 48, row + 4, "expansion region: once per item", "u-n")
x += 232
k.add(f'<path class="u-rake" d="M{x + 6},{row - 6} v10 M{x + 1},{row + 4} v-5 h10 v5"/>')
k.t(x + 22, row + 4, "detailed in its own diagram", "u-n")
row, x = 76, 24
k.add(
    f'<path class="u-note" d="M{x},{row - 12} H{x + 31} L{x + 40},{row - 3} V{row + 12} H{x} z '
    f'M{x + 31},{row - 12} V{row - 3} H{x + 40}"/>'
)
k.t(x + 48, row + 4, "note", "u-n")
x += 96
k.add(f'<path class="u-line" d="M{x},{row} h44" marker-end="url(#u5-a)"/>')
k.t(x + 52, row + 4, "control or object flow · transition", "u-n")
x += 252
k.add(f'<path class="u-line dash" d="M{x},{row} h44" marker-end="url(#u5-a)"/>')
k.t(x + 52, row + 4, "dependency («derive», «trace»)", "u-n")
x += 228
k.add(f'<path class="u-line" d="M{x},{row} h44"/>')
k.t(x + 2, row - 6, "1", "u-mult")
k.t(x + 44, row - 6, "0..*", "u-mult", "end")
k.t(x + 52, row + 4, "association (foreign key)", "u-n")
x += 210
k.add(f'<circle class="u-solid" cx="{x + 6}" cy="{row}" r="5"/>')
k.t(x + 18, row + 4, "junction", "u-n")
x += 80
k.add(f'<circle class="u-node" cx="{x + 11}" cy="{row}" r="11"/>')
k.t(x + 11, row + 4, "H", "u-act", "middle")
k.t(x + 30, row + 4, "history: back to the last state", "u-n")
x += 226
SVG5 = k.svg()


def fig(svg, cap):
    return f"""  <figure>
    <div class="scroll">
{svg}
    </div>
    <figcaption>{cap}</figcaption>
  </figure>"""


SECTION = f"""<section id="inside-the-database">
  <h2>Inside the database, in UML</h2>
{fig(SVG0, "Class diagram: every source, what it delivers (format, contents, how it arrives), the loader that reads it and the raw table that stores it.")}
{fig(SVG1, "Activity diagram: one run of the <code>stock-ingest</code> job, partitioned by who does the work.")}
{fig(SVG2, "Activity diagram: the call behaviour <em>Build fundamentals</em> from the run above, partitioned by step; boxes between actions are the data in each state.")}
{fig(SVG7, "Activity diagram: a change of the extraction is checked on a sample of companies (<code>db check-sample</code>), never by rebuilding the database.")}
{fig(SVG3, "Class diagram: the tables of the data path, with their keys and links (migrations 001 to 010).")}
{fig(SVG4, "State machine: the life of one ingest task, row by row in <code>ops_task</code>.")}
{fig(SVG6, "Activity diagram: a file downloaded by hand loaded into the pipeline (<code>db import</code>).")}
{fig(SVG8, "Activity diagram: what this PC loaded, sent to the server (<code>db push</code>), and the server job's own run.")}
{fig(SVG5, "Key to the symbols (UML 2.5).")}
</section>
"""

CSS = """
/* inside the database (UML) */
.pipeline .u-frame { fill: none; stroke: var(--p-edge); stroke-width: 1; }
.pipeline .u-frame-tag { fill: var(--p-band); stroke: var(--p-edge); stroke-width: 1; }
.pipeline .u-tagk { font: 700 12px var(--p-sans); fill: var(--p-fg); }
.pipeline .u-tag { font: 600 12px var(--p-sans); fill: var(--p-fg); }
.pipeline .u-part { fill: none; stroke: var(--p-edge); stroke-width: 1; }
.pipeline .u-partl { fill: none; stroke: var(--p-edge); stroke-width: 1; }
.pipeline .u-lane { font: 600 11px var(--p-sans); letter-spacing: 0.06em; fill: var(--p-muted); }
.pipeline .u-node { fill: var(--p-card); stroke: var(--p-fg); stroke-width: 1.3; }
.pipeline .u-solid { fill: var(--p-fg); }
.pipeline .u-line { fill: none; stroke: var(--p-fg); stroke-width: 1.2; }
.pipeline .u-line.dash { stroke-dasharray: 5 4; stroke: var(--p-edge); }
.pipeline .u-ah { fill: none; stroke: var(--p-fg); stroke-width: 1.3; }
.pipeline .u-region { fill: none; stroke: var(--p-fg); stroke-width: 1.2; stroke-dasharray: 6 4; }
.pipeline .u-rake { fill: none; stroke: var(--p-fg); stroke-width: 1.3; }
.pipeline .u-note { fill: var(--p-band); stroke: var(--p-edge); stroke-width: 1; }
.pipeline .u-pkg { fill: none; stroke: var(--p-edge); stroke-width: 1.2; }
.pipeline .u-pkgn { font: 600 12px var(--p-sans); fill: var(--p-fg); }
.pipeline .u-act { font: 500 12px var(--p-sans); fill: var(--p-fg); }
.pipeline .u-obj { font: 12px var(--p-sans); fill: var(--p-fg); }
.pipeline .u-objm { font: 11px var(--p-mono); fill: var(--p-fg); }
.pipeline .u-st { font: 11px var(--p-sans); fill: var(--p-muted); }
.pipeline .u-kw { font: 10.5px var(--p-sans); fill: var(--p-muted); }
.pipeline .u-g { font: 11px var(--p-sans); fill: var(--p-fg); }
.pipeline .u-n { font: 11px var(--p-sans); fill: var(--p-fg); }
.pipeline .u-nm { font: 11px var(--p-mono); fill: var(--p-muted); }
.pipeline .u-cname { font: 600 12px var(--p-sans); fill: var(--p-fg); }
.pipeline .u-attr { font: 11px var(--p-mono); fill: var(--p-fg); }
.pipeline .u-mult { font: 11px var(--p-mono); fill: var(--p-muted); }
"""

html = PAGE.read_text(encoding="utf-8")
html = re.sub(r"\n/\* inside the database \((UML)\) \*/.*?(?=</style>)", "\n", html, flags=re.S)
html = html.replace("</style>", CSS.lstrip("\n") + "</style>", 1)
html = re.sub(r'<section id="inside-the-database">.*?</section>\n', "", html, flags=re.S)
anchor = "<section>\n  <h2>One day, in UTC</h2>"
assert anchor in html
html = html.replace(anchor, SECTION + "\n" + anchor, 1)
PAGE.write_text(html, encoding="utf-8")
print("ok", len(html))


# ======================================================================= orchestration
# "The nightly pipeline, in UML": the Airflow DAG stock_nightly (orchestration/dags/), the
# run log it keeps (ops_pipeline_run) and where each piece runs. Follows
# orchestration/dags/stock_nightly.py, src/stock_analysis/pipeline/ and
# .github/workflows/pipeline-watch.yml.


def hourglass(d, cx, cy, label=None, below=True):
    """Accept time event action (UML 2.5): an hourglass."""
    d.add(
        f'<path class="u-node" d="M{cx - 9},{cy - 12} H{cx + 9} L{cx - 9},{cy + 12} H{cx + 9} z"/>'
    )
    if label:
        n = len(label)
        for i, s in enumerate(label):
            y = cy + 28 + 13 * i if below else cy - 18 - 13 * (n - 1 - i)
            d.t(cx, y, s, "u-g", "middle")


def interrupt(d, x1, y1, x2, y2):
    """Interrupting edge (UML 2.5): a zigzag ending in an arrow."""
    mx = (x1 + x2) / 2
    d.add(
        f'<path class="u-line" d="M{x1},{y1} L{mx + 5},{y1} L{mx - 5},{y2} L{x2},{y2}" '
        f'marker-end="url(#{d.p}-a)"/>'
    )


def node3d(d, x, y, w, h, kw, name, depth=10):
    """Deployment node: a box with a top and a right face."""
    d.add(f'<path class="u-node" d="M{x},{y} l{depth},-{depth} h{w} v{h} l-{depth},{depth} z"/>')
    d.add(f'<rect class="u-node" x="{x}" y="{y}" width="{w}" height="{h}"/>')
    d.add(f'<path class="u-line" d="M{x + w},{y} l{depth},-{depth}"/>')
    d.t(x + 10, y + 16, kw, "u-kw")
    d.t(x + 10, y + 31, name, "u-cname")
    return box(x, y, w, h)


def artifact(d, x, y, w, name, kw="«artifact»"):
    h = 38
    d.add(f'<rect class="u-node" x="{x}" y="{y}" width="{w}" height="{h}"/>')
    fx, fy = x + w - 17, y + 6  # the document icon
    d.add(f'<path class="u-line" d="M{fx},{fy} h7 l4,4 v10 h-11 z M{fx + 7},{fy} v4 h4"/>')
    d.t(x + 8, y + 15, kw, "u-kw")
    d.t(x + 8, y + 30, name, "u-attr")
    return box(x, y, w, h)


# ---------------------------------------------------------------- activity: one night
o = D(
    "u7",
    1300,
    660,
    "act",
    "stock_nightly",
    "UML activity diagram of one weekday night in four partitions. Azure runs the ingest job "
    "at 22:30 UTC (fetch, build, coverage, nightly analyses, a row in ops_run) and the quotes "
    "job every hour. Airflow's stock_nightly starts at 22:35 and forks: it checks the quotes "
    "job, waits for the finished ingest run, then forks again to check the nightly analyses "
    "and the prices; the prices lead to the ready marker and to waiting for the Claude "
    "session's commit and its published site. A join closes the run. Any failed check "
    "interrupts the region: the run is marked failed and an alert is emailed. The Claude "
    "session runs at 00:00 Italy time, waits for the newest price, writes the notes and "
    "reports, commits and emails. At 07:00 UTC a GitHub workflow audits the last trading day.",
)
o.frame(10, 10, 1280, 640)
o.add('<rect class="u-part" x="24" y="46" width="1252" height="590"/>')
o.add('<path class="u-partl" d="M24,156 H1276 M24,406 H1276 M50,46 V636"/>')
o.add('<path class="u-partl" d="M24,516 H1276"/>')
o.lane_label(41, 101, "Azure jobs")
o.lane_label(41, 281, "Airflow")
o.lane_label(41, 461, "Claude")
o.lane_label(41, 576, "GitHub")

# lane 1: the ingest job and the quotes job
Y1 = 101
hourglass(o, 82, Y1 - 8, ["22:30 UTC"])
ing = o.action(116, Y1 - 22, 200, 44, ["Ingest, build, coverage,", "nightly analyses"], call=True)
o.edge([(91, Y1 - 8), (ing.l, Y1 - 8)])
opsrun = o.obj(352, Y1 - 20, 110, 40, ["ops_run"], store=True)
o.edge([(ing.r, Y1), (opsrun.l, Y1)])
o.note(
    496,
    62,
    250,
    [
        "its summary records any error of the",
        "screener, the watch-list numbers or",
        "the market numbers",
    ],
    to=(opsrun.r, Y1 - 10),
    frm=(496, Y1 - 10),
)
hourglass(o, 800, Y1 - 8, [":05 hourly", "Mon–Fri"])
qa = o.action(832, Y1 - 20, 130, 40, ["Store the quotes"])
o.edge([(809, Y1 - 8), (qa.l, Y1 - 8)])
qo = o.obj(1000, Y1 - 20, 120, 40, ["raw_tv_quote"], store=True)
o.edge([(qa.r, Y1), (qo.l, Y1)])

# lane 2: Airflow
Y2 = 206
hourglass(o, 82, Y2, ["22:35 UTC", "Mon–Fri"])
st = o.action(108, Y2 - 20, 104, 40, ["Open the", "run log"])
o.edge([(91, Y2), (st.l, Y2)])
RX2, RY2, RW2, RH2 = 232, 166, 908, 230
o.add(f'<rect class="u-region" x="{RX2}" y="{RY2}" width="{RW2}" height="{RH2}" rx="14"/>')
o.t(RX2 + 12, RY2 + 16, "«interruptible»", "u-kw")


def bar(d, x, y1, y2):
    """Fork or join node: a thick bar."""
    d.add(f'<rect class="u-solid" x="{x - 2.5}" y="{y1}" width="5" height="{y2 - y1}"/>')


bar(o, 246, 192, 350)
o.edge([(st.r, Y2), (243.5, Y2)])
wi = o.action(262, Y2 - 20, 116, 40, ["Wait for the", "ingest run"])
o.edge([(248.5, Y2), (wi.l, Y2)])
YQ = 330
cq = o.action(262, YQ - 20, 116, 40, ["Check the", "quotes job"])
o.edge([(248.5, YQ), (cq.l, YQ)])
o.edge([(407, opsrun.b), (407, 180), (350, 180), (350, wi.t)])
o.g(414, 142, "finished row")
o.diamond(412, Y2)
o.edge([(wi.r, Y2), (399, Y2)])
o.edge([(412, Y2 + 13), (412, 262), (290, 262), (290, wi.b)])
o.g(300, 276, "[not yet] / again in 5 min")
bar(o, 446, 192, 312)
o.edge([(425, Y2), (443.5, Y2)])
o.g(430, Y2 - 26, "[done]", "middle")
cp = o.action(466, Y2 - 20, 112, 40, ["Check the", "prices"])
o.edge([(448.5, Y2), (cp.l, Y2)])
YN = 300
cn = o.action(466, YN - 20, 112, 40, ["Check the nightly", "analyses"])
o.edge([(448.5, YN), (cn.l, YN)])
o.diamond(614, Y2)
o.edge([(cp.r, Y2), (601, Y2)])
mr = o.action(662, Y2 - 20, 100, 40, ["Mark ready"])
o.edge([(627, Y2), (mr.l, Y2)])
o.g(640, Y2 + 18, "[≥ 95%", "middle")
o.g(640, Y2 + 31, "fresh]", "middle")
pr = o.obj(650, 282, 124, 40, ["ops_pipeline_run"], store=True)
o.edge([(712, mr.b), (712, pr.t)])
o.g(720, 262, "[ready]")
we = o.action(800, Y2 - 20, 120, 40, ["Wait for commit", "and the site"])
o.edge([(mr.r, Y2), (we.l, Y2)])
o.diamond(956, Y2)
o.edge([(we.r, Y2), (943, Y2)])
o.edge([(956, Y2 + 13), (956, 262), (890, 262), (890, we.b)])
o.g(860, 276, "[not yet] / again in 10 min")
bar(o, 994, 192, 372)
o.edge([(969, Y2), (991.5, Y2)])
o.g(975, Y2 - 26, "[published]", "middle")
o.edge([(cn.r, YN), (620, YN), (620, 352), (991.5, 352)])
o.edge([(cq.r, YQ), (390, YQ), (390, 368), (991.5, 368)])
fi = o.action(1012, Y2 - 20, 86, 40, ["Close the", "run (ok)"])
o.edge([(996.5, Y2), (fi.l, Y2)])
o.final(1120, Y2)
o.edge([(fi.r, Y2), (1109, Y2)])
al = o.action(1166, 238, 98, 44, ["Mark failed,", "email alert"])
interrupt(o, RX2 + RW2, 330, al.l, 260)
o.flow_final(1215, 312)
o.edge([(1215, al.b), (1215, 303)])
o.note(
    1150,
    336,
    120,
    ["a failed check, a", "crash after retries", "or a wait past its", "limit interrupts"],
)

# lane 3: the Claude session
Y3 = 456
hourglass(o, 82, Y3 - 6, ["00:00 Italy", "Tue–Sat"])
wp = o.action(108, Y3 - 26, 150, 40, ["Wait for the newest", "price (up to 1 h)"])
o.edge([(91, Y3 - 6), (wp.l, Y3 - 6)])
nt = o.action(290, Y3 - 28, 160, 44, ["Notes, reports,", "validate"], call=True)
o.edge([(wp.r, Y3 - 6), (nt.l, Y3 - 6)])
cm = o.action(482, Y3 - 26, 120, 40, ["Commit to main"])
o.edge([(nt.r, Y3 - 6), (cm.l, Y3 - 6)])
em = o.action(634, Y3 - 26, 110, 40, ["Email the run"])
o.edge([(cm.r, Y3 - 6), (em.l, Y3 - 6)])
o.final(778, Y3 - 6)
o.edge([(em.r, Y3 - 6), (767, Y3 - 6)])
o.note(
    820,
    426,
    360,
    [
        "docs/EVENING_RUN.md: reads the stored numbers through the",
        "web API, writes the notes, renders the PDFs",
    ],
)

# lane 4: GitHub
Y4 = 576
pg = o.action(472, Y4 - 20, 140, 40, ["Pages publishes", "the site"])
o.edge([(542, cm.b), (542, pg.t)])
o.g(550, 532, "push")
o.flow_final(648, Y4)
o.edge([(pg.r, Y4), (639, Y4)])
o.add(
    f'<path class="u-line dash" d="M{pg.r - 20},{pg.t} V530 H860 V{we.b + 4}" marker-end="url(#u7-a)"/>'
)
o.g(866, 526, "read through the GitHub API")
hourglass(o, 82, Y4, ["07:00 UTC", "Tue–Sat"], below=False)
au = o.action(108, Y4 - 20, 126, 40, ["Audit the last", "trading day"])
o.edge([(91, Y4), (au.l, Y4)])
o.diamond(276, Y4)
o.edge([(au.r, Y4), (263, Y4)])
o.final(276, 620)
o.edge([(276, Y4 + 13), (276, 609)])
o.g(284, 606, "[ok run]")
wf = o.action(318, 556, 126, 40, ["Fail: GitHub", "emails the owner"])
o.edge([(289, Y4), (wf.l, Y4)])
o.g(303, Y4 - 8, "[none]", "middle")
o.flow_final(430, 620)
o.edge([(381, wf.b), (381, 620), (421, 620)])
o.note(
    740,
    560,
    320,
    [
        "pipeline-watch.yml reads ops_pipeline_run through",
        "the web API: it catches a night Airflow never ran",
        "(the PC was off, the DAG paused)",
    ],
)
SVG7 = o.svg()

# ---------------------------------------------------------------- state machine: one run
r = D(
    "u8",
    1300,
    230,
    "stm",
    "ops_pipeline_run",
    "UML state machine of a pipeline run: it starts running, becomes ready when the data "
    "checks pass, and ok when the evening commit is published; a failed step while running "
    "or ready makes it failed. ok and failed are final.",
)
r.frame(10, 10, 1280, 210)
RY = 90
r.initial(60, RY)
ru = r.state(90, RY - 20, 120, 40, "running")
r.edge([(68, RY), (ru.l, RY)])
re_ = r.state(500, RY - 20, 120, 40, "ready")
r.edge([(ru.r, RY), (re_.l, RY)])
r.g(355, RY - 8, "ingest finished, prices fresh / mark_ready", "middle")
ok_ = r.state(890, RY - 20, 120, 40, "ok")
r.edge([(re_.r, RY), (ok_.l, RY)])
r.g(755, RY - 8, "evening commit published / finish", "middle")
r.final(1070, RY)
r.edge([(ok_.r, RY), (1059, RY)])
fa = r.state(500, 160, 120, 40, "failed")
r.edge([(150, ru.b), (150, 180), (fa.l, 180)])
r.g(160, 174, "step failed / email alert")
r.edge([(560, re_.b), (560, fa.t)])
r.g(568, 140, "step failed / email alert")
r.final(680, 180)
r.edge([(fa.r, 180), (669, 180)])
r.note(
    1060,
    130,
    210,
    ["each step is also a row in", ("ops_pipeline_step", "mono"), "(ok, waiting or failed)"],
)
SVG8 = r.svg()

# ---------------------------------------------------------------- deployment
p = D(
    "u9",
    1300,
    520,
    "deployment",
    "Nightly pipeline",
    "UML deployment diagram: Airflow's API server, scheduler, DAG processor and metadata "
    "database run in Docker on the PC with the DAG stock_nightly; Azure runs the ingest and "
    "quotes Container Apps Jobs, the PostgreSQL server stock-db-bk and the web API "
    "stock-api-bk; Anthropic's cloud runs the scheduled Claude session; GitHub runs the "
    "Pages and pipeline-watch workflows; Brevo sends the emails.",
)
p.frame(10, 10, 1280, 500)
pc = node3d(p, 30, 64, 400, 262, "«device»", "PC")
node3d(p, 46, 110, 366, 200, "«executionEnvironment»", "Docker · orchestration/compose.yaml", 8)
artifact(p, 62, 156, 160, "api-server", "«component»")
artifact(p, 236, 156, 160, "scheduler", "«component»")
artifact(p, 62, 206, 160, "dag-processor", "«component»")
artifact(p, 236, 206, 160, "airflow-db", "«database»")
artifact(p, 62, 256, 334, "stock_nightly.py · stock_analysis.pipeline")
az = node3d(p, 500, 64, 400, 300, "«cloud»", "Microsoft Azure")
artifact(p, 516, 106, 360, "stock-ingest · Container Apps Job", "«executionEnvironment»")
artifact(p, 516, 156, 360, "stock-quotes · Container Apps Job", "«executionEnvironment»")
artifact(p, 516, 206, 360, "stock-db-bk · PostgreSQL 16", "«database»")
artifact(p, 516, 256, 360, "stock-api-bk · App Service, api/app.py", "«executionEnvironment»")
p.edge([(876, 125), (888, 125), (888, 275), (876, 275)], arrow=False)  # each one to the database
p.edge([(876, 175), (888, 175)], arrow=False)
p.edge([(876, 225), (888, 225)], arrow=False)
an = node3d(p, 970, 64, 300, 100, "«cloud»", "Anthropic")
artifact(p, 986, 108, 268, "Scheduled Claude session", "«executionEnvironment»")
gh = node3d(p, 970, 230, 300, 150, "«cloud»", "GitHub")
artifact(p, 986, 276, 268, "pages.yml · pipeline-watch.yml", "«workflow»")
artifact(p, 986, 326, 268, "Pages site", "«artifact»")
bv = node3d(p, 500, 420, 220, 70, "«cloud»", "Brevo")
# communication paths
p.edge([(pc.r, 225), (516, 225)], arrow=False)
p.g(473, 218, "SQL · TLS", "middle")
p.edge([(986, 140), (930, 140), (930, 262), (900, 262)], arrow=False)
p.g(936, 190, "HTTPS · data")
p.edge([(1150, an.b), (1150, gh.t - 10)], arrow=False)
p.g(1158, 200, "git push")
p.edge([(380, pc.b), (380, 396), (1100, 396), (1100, gh.b)], arrow=False)
p.g(760, 390, "HTTPS · GitHub API: commit and Pages run", "middle")
p.edge([(200, pc.b), (200, 455), (bv.l, 455)], arrow=False)
p.g(350, 449, "HTTPS · alert email", "middle")
p.edge([(986, 295), (944, 295), (944, 330), (900, 330)], arrow=False)
p.g(950, 320, "HTTPS · audit")
p.edge([(1254, 127), (1282, 127), (1282, 470), (bv.r, 470)], arrow=False)
p.g(800, 464, "HTTPS · evening email")
SVG9 = p.svg()

ORCH = f"""<section id="orchestration">
  <h2>The nightly pipeline, in UML</h2>
{fig(SVG7, "Activity diagram: one weekday night, partitioned by where the work runs; the Airflow DAG <code>stock_nightly</code> waits for each piece and alerts when one fails or doesn't come.")}
{fig(SVG8, "State machine: the status of a run in <code>ops_pipeline_run</code>, the marker the evening session and the morning audit read.")}
{fig(SVG9, "Deployment diagram: the nodes the pipeline runs on and how they talk.")}
</section>
"""

html = PAGE.read_text(encoding="utf-8")
html = re.sub(r'<section id="orchestration">.*?</section>\n\n?', "", html, flags=re.S)
anchor = "<section>\n  <h2>One day, in UTC</h2>"
html = html.replace(anchor, ORCH + "\n" + anchor, 1)
PAGE.write_text(html, encoding="utf-8")
print("orchestration ok")
