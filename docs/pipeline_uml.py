"""Draws the "Inside the database, in UML" section of docs/pipeline.html (four UML 2.5
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
    "plans tasks, chooses its mode and fetches each due task into the raw layer; if rows "
    "were stored the build rebuilds the core layer in one transaction; coverage takes the "
    "snapshot that the next run reads to choose its mode.",
)
a.frame(10, 10, 1280, 600)
a.add('<rect class="u-part" x="24" y="46" width="1252" height="550"/>')
a.add('<path class="u-partl" d="M24,256 H1276 M24,486 H1276 M50,46 V596"/>')
a.lane_label(41, 151, "ingest job")
a.lane_label(41, 371, "db build · one transaction")
a.lane_label(41, 541, "coverage")

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
a.g(1130, CY - 7, "[nothing stored]")

# lane B, right to left
BY, BH = 328, 44
labels = [
    ["Clear core and", "load items, tags"],
    ["Build companies", "and index spells"],
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
a.g(1118, 200, "[rows stored]")
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
rr = a.action(460, CC - 20, 120, 40, ["Record the run"])
a.edge([(out.r, CC), (rr.l, CC)])
a.final(620, CC)
a.edge([(rr.r, CC), (609, CC)])
a.note(
    660,
    500,
    380,
    [
        "ops_run keeps the mode, requests, rows stored,",
        "the build and the coverage summary of each run",
    ],
    to=(rr.r, 525),
    frm=(660, 525),
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

# ======================================================================= notation key
k = D("u5", 1300, 112, "", "", "Key to the UML symbols used in the four diagrams.")
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
{fig(SVG1, "Activity diagram: one run of the <code>stock-ingest</code> job, partitioned by who does the work.")}
{fig(SVG2, "Activity diagram: the call behaviour <em>Build fundamentals</em> from the run above, partitioned by step; boxes between actions are the data in each state.")}
{fig(SVG3, "Class diagram: the tables of the data path, with their keys and links (migrations 001 to 010).")}
{fig(SVG4, "State machine: the life of one ingest task, row by row in <code>ops_task</code>.")}
{fig(SVG6, "Activity diagram: a file downloaded by hand loaded into the pipeline (<code>db import</code>).")}
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
    "UML activity diagram of one weekday night in four partitions. The Azure ingest job runs "
    "at 22:30 UTC and records its run in ops_run. Airflow's stock_nightly starts at 22:35, "
    "opens its run log, waits for the finished ingest run, checks that the prices reached "
    "the last close and marks the run ready. The Claude evening session reads the ready "
    "marker, writes the notes and reports and commits them; GitHub publishes the site; "
    "Airflow waits for that commit and its published site, then closes the run. Any failed "
    "check interrupts the Airflow region: the run is marked failed and an alert is emailed. "
    "At 07:00 UTC a GitHub workflow audits that the last trading day has a finished run.",
)
o.frame(10, 10, 1280, 640)
o.add('<rect class="u-part" x="24" y="46" width="1252" height="590"/>')
o.add('<path class="u-partl" d="M24,156 H1276 M24,396 H1276 M24,516 H1276 M50,46 V636"/>')
o.lane_label(41, 101, "Azure job")
o.lane_label(41, 276, "Airflow")
o.lane_label(41, 456, "Claude")
o.lane_label(41, 576, "GitHub")

# lane 1: the ingest job
Y1 = 101
hourglass(o, 82, Y1 - 8, ["22:30 UTC"])
ing = o.action(116, Y1 - 22, 190, 44, ["Ingest: fetch, build,", "coverage snapshot"], call=True)
o.edge([(91, Y1 - 8), (ing.l, Y1 - 8)])
opsrun = o.obj(350, Y1 - 20, 110, 40, ["ops_run"], store=True)
o.edge([(ing.r, Y1), (opsrun.l, Y1)])
o.note(
    500,
    74,
    340,
    [
        "act Nightly ingest run, above; one row per run with",
        "its mode, status, requests and rows stored",
    ],
    to=(opsrun.r, Y1),
    frm=(500, Y1),
)

# lane 2: Airflow
Y2 = 226
hourglass(o, 82, Y2, ["22:35 UTC", "Mon–Fri"])
st = o.action(108, Y2 - 20, 104, 40, ["Open the", "run log"])
o.edge([(91, Y2), (st.l, Y2)])
RX2, RY2, RW2, RH2 = 236, 168, 904, 218
o.add(f'<rect class="u-region" x="{RX2}" y="{RY2}" width="{RW2}" height="{RH2}" rx="14"/>')
o.t(RX2 + 12, RY2 + 16, "«interruptible»", "u-kw")
wi = o.action(262, Y2 - 20, 116, 40, ["Wait for the", "ingest run"])
o.edge([(st.r, Y2), (wi.l, Y2)])
o.edge([(405, opsrun.b), (405, 190), (340, 190), (340, wi.t)])
o.g(412, 184, "finished row")
o.diamond(420, Y2)
o.edge([(wi.r, Y2), (407, Y2)])
o.edge([(420, Y2 + 13), (420, 282), (300, 282), (300, wi.b)])
o.g(310, 297, "[not yet] / again in 5 min")
cp = o.action(470, Y2 - 20, 112, 40, ["Check the", "prices"])
o.edge([(433, Y2), (cp.l, Y2)])
o.g(451, Y2 - 8, "[done]", "middle")
o.diamond(620, Y2)
o.edge([(cp.r, Y2), (607, Y2)])
mr = o.action(676, Y2 - 20, 100, 40, ["Mark ready"])
o.edge([(633, Y2), (mr.l, Y2)])
o.g(650, Y2 - 40, "[≥ 95% of members", "middle")
o.g(650, Y2 - 27, "have the last close]", "middle")
pr = o.obj(664, 316, 124, 40, ["ops_pipeline_run"], store=True)
o.edge([(726, mr.b), (726, pr.t)])
o.g(734, 296, "[ready]")
we = o.action(826, Y2 - 20, 120, 40, ["Wait for commit", "and the site"])
o.edge([(mr.r, Y2), (we.l, Y2)])
o.diamond(984, Y2)
o.edge([(we.r, Y2), (971, Y2)])
o.edge([(984, Y2 + 13), (984, 282), (926, 282), (926, we.b)])
o.g(936, 297, "[not yet] / again in 10 min")
fi = o.action(1030, Y2 - 20, 92, 40, ["Close the", "run (ok)"])
o.edge([(997, Y2), (fi.l, Y2)])
o.g(1013, Y2 - 27, "[published]", "middle")
o.final(1076, 330)
o.edge([(1076, fi.b), (1076, 319)])
o.note(
    250,
    316,
    360,
    [
        "a failed check, a crash after two retries, or a wait",
        "past its limit (ingest 3.5 h, evening 4 h) interrupts",
        "the region",
    ],
)
al = o.action(1168, 250, 98, 44, ["Mark failed,", "email alert"])
interrupt(o, RX2 + RW2, 352, al.l, 272)
o.flow_final(1217, 346)
o.edge([(1217, al.b), (1217, 337)])

# lane 3: the Claude evening session
Y3 = 446
hourglass(o, 82, Y3 - 6, ["evening", "schedule"])
rm = o.action(108, Y3 - 26, 122, 40, ["Read the ready", "marker (web API)"])
o.edge([(91, Y3 - 6), (rm.l, Y3 - 6)])
o.edge([(726, pr.b), (726, 406), (169, 406), (169, rm.t)])
o.diamond(272, Y3 - 6)
o.edge([(rm.r, Y3 - 6), (259, Y3 - 6)])
nt = o.action(318, Y3 - 28, 160, 44, ["Notes, reports,", "validate"], call=True)
o.edge([(285, Y3 - 6), (nt.l, Y3 - 6)])
o.g(300, Y3 - 14, "[ready]", "middle")
cm = o.action(510, Y3 - 26, 120, 40, ["Commit to main"])
o.edge([(nt.r, Y3 - 6), (cm.l, Y3 - 6)])
em = o.action(662, Y3 - 26, 110, 40, ["Email the run"])
o.edge([(cm.r, Y3 - 6), (em.l, Y3 - 6)])
o.final(806, Y3 - 6)
o.edge([(em.r, Y3 - 6), (795, Y3 - 6)])
sa = o.action(318, 478, 160, 28, ["Say so in the thread"])
o.edge([(272, Y3 + 7), (272, 492), (sa.l, 492)])
o.g(278, 476, "[not ready]")
o.flow_final(506, 492)
o.edge([(sa.r, 492), (497, 492)])
o.note(
    850,
    410,
    320,
    ["docs/EVENING_RUN.md: the PDFs, the notes and", "the screener files are committed to main"],
    to=(nt.r - 10, nt.t),
    frm=(850, 425),
)

# lane 4: GitHub
Y4 = 576
pg = o.action(500, Y4 - 20, 140, 40, ["Pages publishes", "the site"])
o.edge([(570, cm.b), (570, pg.t)])
o.g(578, 532, "push")
o.flow_final(676, Y4)
o.edge([(pg.r, Y4), (667, Y4)])
o.add(
    f'<path class="u-line dash" d="M{pg.r - 20},{pg.t} V530 H876 V{we.b}" marker-end="url(#u7-a)"/>'
)
o.g(880, 526, "read through the GitHub API")
hourglass(o, 82, Y4, ["07:00 UTC", "Tue–Sat"], below=False)
au = o.action(108, Y4 - 20, 126, 40, ["Audit the last", "trading day"])
o.edge([(91, Y4), (au.l, Y4)])
o.diamond(276, Y4)
o.edge([(au.r, Y4), (263, Y4)])
o.final(276, 620)
o.edge([(276, Y4 + 13), (276, 609)])
o.g(284, 606, "[ok run]")
wf = o.action(318, 556, 150, 40, ["Fail: GitHub", "emails the owner"])
o.edge([(289, Y4), (wf.l, Y4)])
o.g(303, Y4 - 8, "[none]", "middle")
o.flow_final(490, 620)
o.edge([(393, wf.b), (393, 620), (481, 620)])
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
    480,
    "deployment",
    "Nightly pipeline",
    "UML deployment diagram: Airflow's API server, scheduler, DAG processor and metadata "
    "database run in Docker on the PC with the DAG stock_nightly; Azure runs the ingest "
    "Container Apps Job, the PostgreSQL server stock-db-bk and the web API stock-api-bk; "
    "Anthropic's cloud runs the Claude evening routine; GitHub runs the Pages and "
    "pipeline-watch workflows; Brevo sends the emails.",
)
p.frame(10, 10, 1280, 460)
pc = node3d(p, 30, 64, 400, 262, "«device»", "PC")
node3d(p, 46, 110, 366, 200, "«executionEnvironment»", "Docker · orchestration/compose.yaml", 8)
artifact(p, 62, 156, 160, "api-server", "«component»")
artifact(p, 236, 156, 160, "scheduler", "«component»")
artifact(p, 62, 206, 160, "dag-processor", "«component»")
artifact(p, 236, 206, 160, "airflow-db", "«database»")
artifact(p, 62, 256, 334, "stock_nightly.py · stock_analysis.pipeline")
az = node3d(p, 500, 64, 400, 222, "«cloud»", "Microsoft Azure")
artifact(p, 516, 110, 368, "stock-ingest · Container Apps Job", "«executionEnvironment»")
artifact(p, 516, 168, 368, "stock-db-bk · PostgreSQL 16", "«database»")
artifact(p, 516, 226, 368, "stock-api-bk · App Service, api/app.py", "«executionEnvironment»")
an = node3d(p, 970, 64, 300, 100, "«cloud»", "Anthropic")
artifact(p, 986, 108, 268, "Evening watch list routine", "«executionEnvironment»")
gh = node3d(p, 970, 230, 300, 150, "«cloud»", "GitHub")
artifact(p, 986, 276, 268, "pages.yml · pipeline-watch.yml", "«workflow»")
artifact(p, 986, 326, 268, "Pages site", "«artifact»")
bv = node3d(p, 500, 380, 220, 70, "«cloud»", "Brevo")
# communication paths
p.edge([(pc.r, 187), (516, 187)], arrow=False)
p.g(473, 180, "SQL · TLS", "middle")
p.edge([(700, 148), (700, 168)], arrow=False)
p.edge([(700, 206), (700, 226)], arrow=False)
p.edge([(986, 140), (930, 140), (930, 240), (884, 240)], arrow=False)
p.g(936, 184, "HTTPS · marker")
p.edge([(1150, an.b), (1150, gh.t - 10)], arrow=False)
p.g(1158, 200, "git push")
p.edge([(380, pc.b), (380, 356), (gh.l, 356)], arrow=False)
p.g(760, 350, "HTTPS · GitHub API: commit and Pages run", "middle")
p.edge([(200, pc.b), (200, 415), (bv.l, 415)], arrow=False)
p.g(350, 409, "HTTPS · alert email", "middle")
p.edge([(986, 295), (910, 295), (910, 256), (884, 256)], arrow=False)
p.g(916, 310, "HTTPS · audit")
p.edge([(1254, 127), (1282, 127), (1282, 430), (bv.r, 430)], arrow=False)
p.g(800, 424, "HTTPS · evening email")
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
