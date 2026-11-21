"""Split-flap board for a GitHub profile README, in GitHub's own code-block colors.

Every character sits on its own tile with a hinge. The board rotates between
pages (DEPARTURES: repos and how stale they are, ARRIVALS: the latest commit of
each repo, DISRUPTION: the joke page, ALL ABOARD: a drawing). When a tile's character changes it
flutters through two random characters, a flap falling across it each time.
Tiles that read the same on consecutive pages stay still.

Reads the data from the GitHub API (public, non-fork repos only) and writes
light.svg and dark.svg. A GITHUB_TOKEN in the environment lifts the rate limit.
Usage: python3 generate.py <out_dir>
"""
import json
import os
import random
import re
import sys
import urllib.request
from datetime import date, datetime, timedelta, timezone
from itertools import combinations
from pathlib import Path
from xml.sax.saxutils import escape

TODAY = datetime.now(timezone.utc).date()
MONTHS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]
USER = "Sn4pe"
SHOWN = 7  # repos on the board, most recently pushed first

# Short cargo lines; a repo not listed here shows its GitHub description instead.
CARGO = {
    "renfe-tui": "train times in your terminal",
    "accioshot": "screenshots for Linux",
    "nixos-config": "my NixOS setup",
    "hyprglance": "window switcher for Hyprland",
    "noctalia-plugins": "Noctalia shell plugins",
    "infographic-studio": "technical figure composer",
    "ribbit": "generative art from any seed",
}

# (repo, what it carries, last push, last commit date, short sha, last commit subject), filled by fetch()
REPOS = []


def api(path):
    req = urllib.request.Request(f"https://api.github.com/{path}", headers={"Accept": "application/vnd.github+json"})
    if os.environ.get("GITHUB_TOKEN"):
        req.add_header("Authorization", f"Bearer {os.environ['GITHUB_TOKEN']}")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def fetch():
    repos = [r for r in api(f"users/{USER}/repos?type=owner&sort=pushed&per_page=100")
             if not (r["fork"] or r["private"] or r["archived"] or r["name"].lower() == USER.lower())]
    rows = []
    for r in repos[:SHOWN]:
        # merge commits say nothing about the work, so arrivals show the latest real one
        commit = next(c for c in api(f"repos/{USER}/{r['name']}/commits?per_page=30") if len(c["parents"]) == 1)
        rows.append((r["name"], CARGO.get(r["name"], r["description"] or ""),
                     date.fromisoformat(r["pushed_at"][:10]),
                     date.fromisoformat(commit["commit"]["committer"]["date"][:10]),
                     commit["sha"][:7], commit["commit"]["message"].splitlines()[0]))
    assert len(rows) == SHOWN, "every page needs the same number of rows"
    return rows


# The joke page, hand-written: (time, destination, reason, status, color class)
DISRUPTION = [
    ("03:00", "bed", "one more commit first", "CANCELLED", "rd"),
    ("NOW", "new side project", "departs from platform 9 3/4", "ON TIME", "gr"),
    ("LATER", "old side projects", "leaves on the line", "DELAYED", "am"),
    ("SOON", "documentation", "this service does not stop here", "NOT STOPPING", "tx"),
    (str(TODAY.year + 1), "the Linux desktop", "expected every year since 1999", "DELAYED", "am"),
    ("--:--", "vim", "passengers unable to exit", "HELD", "tx"),
    ("TODAY", "touch grass", "replaced by a bus", "SEE BUS", "am"),
]

# The drawing page: a steam train where each column of the board is one vehicle.
# One tuple per row of tiles (the header row first, used for smoke), one string per column.
TRAIN = [
    ("", "", "        .     .    o     o   O", " O"),
    ("", "", "", "    O o"),
    ("", "", "", "____   __"),
    ("_____", " " + "_" * 16, " " + "_" * 30, "|  |   ||"),
    ("  [] |", "| [] [] [] [] [] |", "|  [] [] [] [] [] [] [] [] []  |", "|[]|___||___"),
    ("     |", "|" + " " * 16 + "|", "|" + "SN4PE EXPRESS".center(30) + "|", "|  |        )"),
    ("_____|", "|" + "_" * 16 + "|", "|" + "_" * 30 + "|", "|__|________)"),
    ("O)(O)", " (O)(O)    (O)(O)", " (O)(O)" + " " * 18 + "(O)(O)", "(O)-(O)-(O)_\\"),
]

# GitHub Primer colors: bg is the code-block background, tile sits just off it.
THEMES = {
    "light": dict(bg="#f6f8fa", tile="#e4e9ee", flap="#c3ccd6", fg="#1f2328", tx="#3a424b", mu="#59636e",
                  gr="#1a7f37", am="#9a6700", rd="#d1242f"),
    "dark": dict(bg="#151b23", tile="#0b0f14", flap="#2f3945", fg="#f0f6fc", tx="#c9d1d9", mu="#9198a1",
                 gr="#3fb950", am="#d29922", rd="#f85149"),
}

GROUPS = [6, 18, 32, 13]  # tiles per column: date, name, text, status
PITCH, TILE_W, TILE_H, ROW, GAP, PAD_X = 11, 10, 20, 24, 8, 24
TITLE_TOP, RULE_Y, BODY_TOP = 16, 51, 60
HOLD, FLAP, FLAPS = 10, 0.14, 3  # seconds a page stays up; seconds one flap takes; flaps per change
LEAD = 6  # seconds skipped at load, so the first rotation comes after ~3 s instead of ~9 s
SCRAMBLE = "ABCDEFGHJKLMNPQRSTUVWXYZ0123456789"
FONT = "ui-monospace,SFMono-Regular,'SF Mono',Menlo,Consolas,'Liberation Mono',monospace"

STARTS = [sum(GROUPS[:i]) for i in range(len(GROUPS))]
GROUP_X = [PAD_X + STARTS[i] * PITCH + i * GAP for i in range(len(GROUPS))]
W = GROUP_X[-1] + GROUPS[-1] * PITCH - (PITCH - TILE_W) + PAD_X
BODY_XS = [GROUP_X[g] + i * PITCH + TILE_W / 2 for g, n in enumerate(GROUPS) for i in range(n)]
TITLE_XS = [PAD_X + i * PITCH + TILE_W / 2 for i in range(10)]


def fmt(d):
    return f"{d.day:02d} {MONTHS[d.month - 1]}"


def status(pushed):
    """Delay is days since the last push. Returns (text, color class, diff marker)."""
    days = (TODAY - pushed).days
    if days <= 2:
        return "ON TIME", "gr", "+"
    if days <= 90:
        return f"DELAYED {days} D", "am", "!"
    return "ARRIVED", "tx", " "  # an old repo is a train that got there, not one rotting in a depot


def clip(text, width):
    return text if len(text) <= width else text[: width - 3].rstrip() + "..."


def row(*texts_and_classes):
    """Lay one (text, class) per column onto a row of tiles: {tile index: (char, class)}."""
    cells = {}
    for group, (text, cls) in enumerate(texts_and_classes):
        for i, ch in enumerate(clip(text.upper(), GROUPS[group])):
            if ch != " ":
                cells[STARTS[group] + i] = (ch, cls)
    return cells


def head(*labels):
    return row(*[(label, "mu") for label in labels])


def art(lines):
    """Rows of tiles from a drawing, kept as typed (no upper-casing). The header row is the dim one."""
    return [{STARTS[g] + i: (ch, "mu" if r == 0 else "tx")
             for g, part in enumerate(parts) for i, ch in enumerate(part) if ch != " "}
            for r, parts in enumerate(lines)]


def pages():
    """[(title, rows)] in rotation order. Every page has one header row plus len(REPOS) rows."""
    departures = [head("PUSHED", "DESTINATION", "CARGO", "STATUS")]
    for name, cargo, pushed, *_ in REPOS:
        st, cls, _ = status(pushed)
        departures.append(row((fmt(pushed), "fg"), (name, "fg b"), (cargo, "tx"), (st, cls)))
    arrivals = [head("LANDED", "FROM", "COMMIT", "HASH")]
    for name, _, _, landed, sha, subject in sorted(REPOS, key=lambda r: r[3], reverse=True):
        arrivals.append(row((fmt(landed), "fg"), (name, "fg b"), (subject, "tx"), (sha, "gr")))
    disruption = [head("TIME", "DESTINATION", "REASON", "STATUS")]
    for when, where, why, st, cls in DISRUPTION:
        disruption.append(row((when, "fg"), (where, "fg b"), (why, "tx"), (st, cls)))
    return [("DEPARTURES", departures), ("ARRIVALS", arrivals), ("DISRUPTION", disruption), ("ALL ABOARD", art(TRAIN))]


def visible(*intervals):
    """Step-end keyframes showing an element inside [start, end) %. Paired stops can round together and fade."""
    k = [f"0%{{opacity:{int(intervals[0][0] == 0)}}}"]
    for s, e in intervals:
        if s > 0:
            k.append(f"{s:.3f}%{{opacity:1}}")
        if e < 100:
            k.append(f"{e:.3f}%{{opacity:0}}")
    k.append(f"100%{{opacity:{int(intervals[-1][1] == 100)}}}")
    return "".join(k)


def css(c, n):
    """n pages. Transition k turns page k into page k+1 (the last one back into page 0)."""
    loop = HOLD * n
    pct = lambda seconds: seconds / loop * 100
    flap = pct(FLAP)
    start = [pct((k + 1) * HOLD - 0.8) for k in range(n)]  # where each transition begins, in %
    swap = [[s + (i + 0.5) * flap for i in range(FLAPS)] for s in start]  # moments the glyph changes
    rules, frames = [], []

    def add(name, keyframes):
        stops = [float(x) for x in re.findall(r"([\d.]+)%", keyframes)]
        assert stops == sorted(set(stops)), f"{name}: keyframes at the same percentage merge into one"
        rules.append(f".{name}{{animation-name:{name}}}")
        frames.append(f"@keyframes {name}{{{keyframes}}}")

    # v<i><o>: a glyph that flips in on transition i and out on transition o
    for i in range(n):
        for o in range(n):
            if i != o:
                on, off = swap[i][-1], swap[o][0]
                add(f"v{i}{o}", visible((on, off)) if on < off else visible((0, off), (on, 100)))
    # p/q/f<set>: the two fluttering glyphs and the falling flap, for tiles that change on that set of transitions
    rest, up = "opacity:0;transform:scaleY(1)", "opacity:.9;transform:scaleY"
    for size in range(2, n + 1):
        for active in combinations(range(n), size):
            key = "".join(map(str, active))
            add(f"p{key}", visible(*[(swap[k][0], swap[k][1]) for k in active]))
            add(f"q{key}", visible(*[(swap[k][1], swap[k][2]) for k in active]))
            fall = ["0%{" + rest + "}"]
            for k in active:
                fall.append(f"{start[k] - 0.01:.3f}%{{{rest}}}")
                for i in range(FLAPS):  # drops from above the hinge (1) through edge-on (0) to below it (-1)
                    t = start[k] + i * flap
                    fall.append(f"{t:.3f}%{{{up}(1)}}{t + flap / 2:.3f}%{{{up}(0)}}{t + flap - 0.01:.3f}%{{{up}(-1)}}")
                fall.append(f"{start[k] + FLAPS * flap:.3f}%{{{rest}}}")
            add(f"f{key}", "".join(fall) + "100%{" + rest + "}")
    return (
        f"text{{font:500 14px {FONT};text-anchor:middle}}"
        f".b{{font-weight:700}}.s{{font:400 13px {FONT};text-anchor:start}}.e{{font:400 13px {FONT};text-anchor:end}}"
        f".fg{{fill:{c['fg']}}}.tx{{fill:{c['tx']}}}.mu,.sc{{fill:{c['mu']}}}.gr{{fill:{c['gr']}}}.am{{fill:{c['am']}}}.rd{{fill:{c['rd']}}}"
        f".fl{{fill:{c['flap']};transform-box:fill-box;transform-origin:50% 100%}}"
        # k: anything animated. o: what shows on page one, so it is also what a still image shows.
        # glyphs jump (step-end); only the falling flap moves smoothly
        f".k{{opacity:0;animation:{loop}s step-end infinite;animation-delay:var(--d)}}.o{{opacity:1}}"
        ".fl.k{animation-timing-function:linear}"
        + "".join(rules) + "".join(frames)
        + "@media (prefers-reduced-motion:reduce){.k{animation:none}}"
    )


def tiles(rows, xs, r, rng):
    """One row of glyphs. rows holds that row on each page, xs the tile centers."""
    n, out = len(rows), []
    for col, x in enumerate(xs):
        glyphs = [page_row.get(col) for page_row in rows]
        if not any(glyphs):
            continue
        active = [k for k in range(n) if glyphs[k] != glyphs[(k + 1) % n]]
        if not active:  # reads the same on every page: this flap never moves
            out.append(f'<text class="{glyphs[0][1]}" x="{x:g}">{escape(glyphs[0][0])}</text>')
            continue
        key = "".join(map(str, active))
        delay = r * 0.18 + col * 0.02 + rng.random() * 0.25 - LEAD
        g = f'<g transform="translate({x:g})" style="--d:{delay:.2f}s">'
        for idx, k_in in enumerate(active):  # one glyph per stretch of pages that read the same
            k_out = active[(idx + 1) % len(active)]
            glyph = glyphs[(k_in + 1) % n]
            if glyph:
                first = " o" if k_out < k_in or (k_in + 1) % n == 0 else ""  # this stretch covers page one
                g += f'<text class="{glyph[1]} k v{k_in}{k_out}{first}">{escape(glyph[0])}</text>'
        g += (f'<text class="sc k p{key}">{rng.choice(SCRAMBLE)}</text><text class="sc k q{key}">{rng.choice(SCRAMBLE)}</text>'
              f'<rect class="fl k f{key}" x="-{TILE_W / 2:g}" y="-15" width="{TILE_W}" height="{TILE_H / 2:g}"/></g>')
        out.append(g)
    return "".join(out)


def svg(theme):
    c = THEMES[theme]
    book = pages()
    n = len(book)
    rng = random.Random(4)  # fixed seed: same data, same SVG
    n_rows = len(book[0][1])
    body_h = n_rows * ROW - (ROW - TILE_H)
    rule_y2 = BODY_TOP + body_h + 17
    h = rule_y2 + 36
    right = f"github.com/{USER} · updated {fmt(TODAY)} {TODAY.year}"
    rule = lambda ch, y: (f'<text class="mu s" x="{PAD_X}" y="{y}" textLength="{W - 2 * PAD_X}" '
                          f'lengthAdjust="spacing">{ch * 98}</text>')
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {h}" width="{W}" height="{h}" role="img" '
        f'aria-label="Split-flap board that rotates between {USER}\'s repositories as departing trains, '
        f'delayed by the days since their last push, the latest commit to land in each one, a page of jokes, and an ASCII steam train">',
        f"<style>{css(c, n)}</style>",
        "<defs>"
        f'<pattern id="t" width="{PITCH}" height="{ROW}" patternUnits="userSpaceOnUse">'
        f'<rect width="{TILE_W}" height="{TILE_H}" rx="1.5" fill="{c["tile"]}"/>'
        f'<rect y="{TILE_H / 2 - 0.5:g}" width="{TILE_W}" height="1" fill="{c["bg"]}"/></pattern>'
        f'<pattern id="h" width="{PITCH}" height="{ROW}" patternUnits="userSpaceOnUse">'
        f'<rect y="{TILE_H / 2 - 0.5:g}" width="{TILE_W}" height="1" fill="{c["tile"]}" opacity=".3"/></pattern>'
        "</defs>",
        f'<rect width="{W}" height="{h}" rx="6" fill="{c["bg"]}"/>',
    ]
    # tile backs, glyphs, then a faint trace of the hinge over the glyphs
    blocks = [(PAD_X, TITLE_TOP, 10, TILE_H)] + [(x, BODY_TOP, cols, body_h) for x, cols in zip(GROUP_X, GROUPS)]
    backs = lambda fill: "".join(
        f'<rect transform="translate({x} {y})" width="{cols * PITCH - 1}" height="{bh}" fill="url(#{fill})"/>'
        for x, y, cols, bh in blocks)
    out.append(backs("t"))
    titles = [{i: (ch, "fg b") for i, ch in enumerate(title)} for title, _ in book]
    out.append(f'<g transform="translate(0 {TITLE_TOP + 15})">{tiles(titles, TITLE_XS, 0, rng)}</g>')
    for r in range(n_rows):
        rows = [page_rows[r] for _, page_rows in book]
        out.append(f'<g transform="translate(0 {BODY_TOP + r * ROW + 15})">{tiles(rows, BODY_XS, r + 1, rng)}</g>')
    out.append(backs("h"))
    out.append(f'<text class="mu e" x="{W - PAD_X}" y="{TITLE_TOP + 15}">{escape(right)}</text>')
    out.append(rule("=", RULE_Y))
    out.append(rule("-", rule_y2))
    out.append(f'<text class="mu s" x="{PAD_X}" y="{rule_y2 + 20}">'
               'delay = days since the last push · arrivals = the latest commit in each repo</text>')
    out.append("</svg>")
    return "\n".join(out)


if __name__ == "__main__":
    ago = lambda days: TODAY - timedelta(days=days)
    assert status(TODAY)[0] == "ON TIME" and status(ago(11))[0] == "DELAYED 11 D" and status(ago(116))[0] == "ARRIVED"
    REPOS[:] = fetch()
    out_dir = Path(sys.argv[1])
    for theme in THEMES:
        (out_dir / f"{theme}.svg").write_text(svg(theme), encoding="utf-8")
    assert len({len(rows) for _, rows in pages()}) == 1, "every page needs the same number of rows"
    assert all(len(title) <= 10 for title, _ in pages())
    assert all(len(text) <= width for joke in DISRUPTION for text, width in zip(joke, GROUPS)), "a joke does not fit its column"
    assert all(len(part) <= width for parts in TRAIN for part, width in zip(parts, GROUPS)), "the drawing does not fit its columns"
