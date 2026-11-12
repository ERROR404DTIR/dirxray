#!/usr/bin/env python3
"""dirxray - X-ray any folder. One file, zero installs (Python 3.8+, stdlib only).

Usage:
    python dirxray.py [path] [--html report.html] [--json] [--open]
                      [--top N] [--fail-under SCORE]
"""
import argparse
import hashlib
import json
import os
import re
import sys
import time
import webbrowser
from collections import Counter, defaultdict
from html import escape

__version__ = "1.0.0"

LANGS = {
    ".py": "Python", ".js": "JavaScript", ".jsx": "JavaScript", ".mjs": "JavaScript",
    ".ts": "TypeScript", ".tsx": "TypeScript", ".java": "Java", ".kt": "Kotlin",
    ".c": "C", ".h": "C", ".cpp": "C++", ".hpp": "C++", ".cs": "C#", ".go": "Go",
    ".rs": "Rust", ".rb": "Ruby", ".php": "PHP", ".swift": "Swift", ".dart": "Dart",
    ".lua": "Lua", ".sh": "Shell", ".bat": "Batch", ".ps1": "PowerShell",
    ".html": "HTML", ".css": "CSS", ".scss": "CSS", ".vue": "Vue", ".svelte": "Svelte",
    ".json": "JSON", ".yml": "YAML", ".yaml": "YAML", ".toml": "TOML", ".xml": "XML",
    ".sql": "SQL", ".md": "Markdown", ".txt": "Text",
}
SKIP_DIRS = {
    ".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build", ".idea",
    ".vscode", ".next", "target", ".mypy_cache", ".tox", ".pytest_cache",
}
MAX_READ = 2_000_000   # don't read text files bigger than this
BIG_FILE = 5_000_000   # flag files bigger than this
MIN_DUP = 32           # ignore tiny duplicate files

SECRET_RULES = [
    ("AWS access key", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("GitHub token", re.compile(r"gh[pousr]_[A-Za-z0-9]{36,}")),
    ("Slack token", re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}")),
    ("Google API key", re.compile(r"AIza[0-9A-Za-z_\-]{35}")),
    ("Private key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----")),
    ("Hardcoded secret", re.compile(
        r"(?i)(?:password|passwd|secret|api[_-]?key|token)\s*[:=]\s*['\"][^'\"\s]{8,}['\"]")),
]
TODO_RE = re.compile(r"\b(" + "|".join(("TO" + "DO", "FIX" + "ME", "HA" + "CK", "X" * 3)) + r")\b")


def mask(s):
    return s[:4] + "..." + s[-2:] if len(s) > 10 else "***"


def fmt_size(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024


def file_hash(path):
    h = hashlib.blake2b(digest_size=16)
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def scan(root):
    t0 = time.time()
    root = os.path.abspath(root)
    has = {
        "git": os.path.isdir(os.path.join(root, ".git")),
        "readme": False, "license": False, "gitignore": False,
    }
    lang_lines, lang_files = Counter(), Counter()
    todos, secrets, bigs = [], [], []
    by_size = defaultdict(list)
    n_files = total_bytes = total_lines = 0

    for dp, dn, fn in os.walk(root):
        dn[:] = [d for d in dn if d not in SKIP_DIRS]
        for name in fn:
            p = os.path.join(dp, name)
            try:
                if os.path.islink(p):
                    continue
                size = os.path.getsize(p)
            except OSError:
                continue
            rel = os.path.relpath(p, root)
            n_files += 1
            total_bytes += size
            if dp == root:
                low = name.lower()
                has["readme"] |= low.startswith("readme")
                has["license"] |= low.startswith(("license", "licence", "copying"))
                has["gitignore"] |= low == ".gitignore"
            if size > BIG_FILE:
                bigs.append((rel, size))
            if size >= MIN_DUP:
                by_size[size].append(p)
            if size == 0 or size > MAX_READ:
                continue
            try:
                with open(p, "rb") as f:
                    data = f.read()
            except OSError:
                continue
            if b"\0" in data[:4096]:
                continue
            lines = data.decode("utf-8", "replace").splitlines()
            total_lines += len(lines)
            lang = LANGS.get(os.path.splitext(name)[1].lower())
            if lang:
                lang_lines[lang] += len(lines)
                lang_files[lang] += 1
            for i, line in enumerate(lines, 1):
                if len(line) > 1000:
                    continue
                if TODO_RE.search(line):
                    todos.append((rel, i, line.strip()[:100]))
                for label, rx in SECRET_RULES:
                    m = rx.search(line)
                    if m:
                        secrets.append((rel, i, label, mask(m.group(0))))
                        break

    dups, wasted = [], 0
    for size, paths in by_size.items():
        if len(paths) < 2:
            continue
        groups = defaultdict(list)
        for p in paths:
            try:
                groups[file_hash(p)].append(os.path.relpath(p, root))
            except OSError:
                pass
        for g in groups.values():
            if len(g) > 1:
                dups.append((size, sorted(g)))
                wasted += size * (len(g) - 1)
    dups.sort(key=lambda d: -d[0] * (len(d[1]) - 1))
    bigs.sort(key=lambda b: -b[1])

    code_total = sum(lang_lines.values()) or 1
    lang_rows = [(l, n, 100 * n / code_total) for l, n in lang_lines.most_common()]

    r = {
        "root": root, "files": n_files, "bytes": total_bytes, "lines": total_lines,
        "langs": lang_rows, "lang_files": dict(lang_files),
        "secrets": secrets, "todos": todos, "big_files": bigs,
        "duplicates": dups, "wasted_bytes": wasted, "has": has,
        "seconds": round(time.time() - t0, 2),
    }
    r["score"], r["penalties"] = health(r)
    r["grade"] = "A" if r["score"] >= 90 else "B" if r["score"] >= 80 else \
        "C" if r["score"] >= 70 else "D" if r["score"] >= 60 else "F"
    return r


def health(r):
    s, pen = 100, []

    def hit(points, why):
        nonlocal s
        if points > 0:
            s -= points
            pen.append((points, why))

    hit(min(40, 8 * len(r["secrets"])), f"{len(r['secrets'])} possible secret(s)")
    hit(min(15, r["wasted_bytes"] // 500_000) + min(5, len(r["duplicates"])),
        f"{len(r['duplicates'])} duplicate group(s), {fmt_size(r['wasted_bytes'])} wasted")
    hit(min(15, 5 * len(r["big_files"])), f"{len(r['big_files'])} file(s) over {fmt_size(BIG_FILE)}")
    density = len(r["todos"]) / max(1, r["lines"] / 1000)
    hit(min(10, int(density)), f"{len(r['todos'])} task marker(s)")
    if not r["has"]["readme"]:
        hit(5, "no README")
    if not r["has"]["license"]:
        hit(3, "no LICENSE")
    if r["has"]["git"] and not r["has"]["gitignore"]:
        hit(2, "no .gitignore")
    return max(0, s), pen


# ---------- terminal ----------

def print_report(r, top):
    color = sys.stdout.isatty() and not os.environ.get("NO_COLOR")

    def c(code, text):
        return f"\033[{code}m{text}\033[0m" if color else text

    sc = r["score"]
    tone = "32" if sc >= 80 else "33" if sc >= 60 else "31"
    print(c("1;36", "\n dirxray") + c("2", "  |  ") + os.path.basename(r["root"]) or r["root"])
    print(f" Health  {c('1;' + tone, str(sc) + '/100')}  ({r['grade']})")
    print(f" Files {r['files']:,}  |  Lines {r['lines']:,}  |  Size {fmt_size(r['bytes'])}"
          f"  |  {r['seconds']}s\n")
    for lang, n, pct in r["langs"][:top]:
        bar = "#" * int(pct / 100 * 24)
        print(f" {lang:<12} {c('36', bar):<{24 + (9 if color else 0)}} {pct:5.1f}%  {n:,} lines")
    sections = [
        ("Possible secrets", r["secrets"], lambda x: f"{x[0]}:{x[1]}  {x[2]}  {x[3]}", "31"),
        ("Duplicate files", r["duplicates"],
         lambda x: f"{fmt_size(x[0])} x{len(x[1])}  {', '.join(x[1][:3])}", "33"),
        ("Big files", r["big_files"], lambda x: f"{fmt_size(x[1])}  {x[0]}", "33"),
        ("Task markers", r["todos"], lambda x: f"{x[0]}:{x[1]}  {x[2]}", "34"),
    ]
    for title, items, show, tone in sections:
        print(f"\n {c('1;' + tone, title)} ({len(items)})")
        for it in items[:top]:
            print("   - " + show(it))
        if len(items) > top:
            print(c("2", f"   ... +{len(items) - top} more (use --top or --html)"))
    if r["penalties"]:
        print("\n " + c("1", "Score penalties"))
        for pts, why in r["penalties"]:
            print(f"   -{pts:<3} {why}")
    print()


# ---------- html ----------

HTML = """<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>dirxray report</title>
<style>
:root{--bg:#0b1020;--card:#121a33;--fg:#e2e8f0;--mut:#94a3b8;--a:#22d3ee;--b:#a78bfa}
*{box-sizing:border-box}
body{margin:0 auto;max-width:960px;padding:32px 20px;font:15px/1.5 system-ui,sans-serif;background:var(--bg);color:var(--fg)}
h1{font-size:30px;margin:0;background:linear-gradient(90deg,var(--a),var(--b));-webkit-background-clip:text;background-clip:text;color:transparent}
h2{margin:30px 0 8px;font-size:18px}.mut{color:var(--mut)}
.top{display:flex;align-items:center;gap:24px;flex-wrap:wrap;margin:18px 0}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;flex:1}
.card{background:var(--card);border-radius:14px;padding:14px 16px}.card b{display:block;font-size:22px}
.ring circle{fill:none;stroke-width:10;stroke-linecap:round}.track{stroke:#1e293b}
.val{stroke-dasharray:339.3;stroke-dashoffset:339.3;transform:rotate(-90deg);transform-origin:center;animation:fill 1.4s ease-out forwards}
@keyframes fill{to{stroke-dashoffset:var(--off)}}
.bar{height:10px;border-radius:6px;background:#1e293b;overflow:hidden}
.bar i{display:block;height:100%;width:0;background:linear-gradient(90deg,var(--a),var(--b));animation:grow 1.1s ease-out forwards}
@keyframes grow{to{width:var(--w)}}
table{width:100%;border-collapse:collapse}td,th{text-align:left;padding:6px 8px;border-bottom:1px solid #1e293b;word-break:break-all}
th{color:var(--mut);font-weight:500}code{color:var(--a)}
</style>
<h1>dirxray</h1><div class="mut">%%ROOT%% &middot; scanned in %%SECS%%s</div>
<div class="top">
<svg class="ring" width="130" height="130" viewBox="0 0 120 120">
<defs><linearGradient id="g"><stop offset="0" stop-color="#22d3ee"/><stop offset="1" stop-color="#a78bfa"/></linearGradient></defs>
<circle class="track" cx="60" cy="60" r="54"/>
<circle class="val" cx="60" cy="60" r="54" stroke="url(#g)" style="--off:%%OFF%%"/>
<text x="60" y="66" text-anchor="middle" font-size="28" font-weight="700" fill="%%COL%%">%%SCORE%%</text>
<text x="60" y="86" text-anchor="middle" font-size="12" fill="#94a3b8">grade %%GRADE%%</text></svg>
<div class="grid">
<div class="card"><b>%%FILES%%</b><span class="mut">files</span></div>
<div class="card"><b>%%LINES%%</b><span class="mut">lines</span></div>
<div class="card"><b>%%SIZE%%</b><span class="mut">total size</span></div>
<div class="card"><b>%%WASTE%%</b><span class="mut">duplicate waste</span></div></div></div>
%%BODY%%
<p class="mut" style="margin-top:36px">Generated by dirxray %%VER%%</p></html>
"""


def _table(title, headers, rows):
    out = [f"<h2>{escape(title)} <span class='mut'>({len(rows)})</span></h2>"]
    if not rows:
        return out[0] + "<p class='mut'>Nothing found.</p>"
    head = "".join(f"<th>{escape(h)}</th>" for h in headers)
    body = "".join("<tr>" + "".join(f"<td>{escape(str(c))}</td>" for c in row) + "</tr>" for row in rows)
    return out[0] + f"<table><tr>{head}</tr>{body}</table>"


def render_html(r, top=50):
    lang_rows = "".join(
        f"<tr><td>{escape(l)}</td><td style='width:55%'><div class='bar'><i style='--w:{p:.1f}%'></i></div></td>"
        f"<td>{n:,}</td><td>{p:.1f}%</td></tr>" for l, n, p in r["langs"])
    body = f"<h2>Languages</h2><table>{lang_rows}</table>" if lang_rows else ""
    body += _table("Possible secrets", ["File", "Line", "Type", "Match"],
                   [(a, b, c, d) for a, b, c, d in r["secrets"][:top]])
    body += _table("Duplicate files", ["Size", "Copies", "Files"],
                   [(fmt_size(s), len(g), ", ".join(g[:4])) for s, g in r["duplicates"][:top]])
    body += _table("Big files", ["Size", "File"], [(fmt_size(s), f) for f, s in r["big_files"][:top]])
    body += _table("Task markers", ["File", "Line", "Text"], r["todos"][:top])
    body += _table("Score penalties", ["Points", "Reason"], [(f"-{p}", w) for p, w in r["penalties"]])
    col = "#4ade80" if r["score"] >= 80 else "#facc15" if r["score"] >= 60 else "#f87171"
    rep = {
        "ROOT": escape(r["root"]), "SECS": r["seconds"], "OFF": f"{339.3 * (1 - r['score'] / 100):.1f}",
        "COL": col, "SCORE": r["score"], "GRADE": r["grade"], "FILES": f"{r['files']:,}",
        "LINES": f"{r['lines']:,}", "SIZE": fmt_size(r["bytes"]), "WASTE": fmt_size(r["wasted_bytes"]),
        "BODY": body, "VER": __version__,
    }
    page = HTML
    for k, v in rep.items():
        page = page.replace(f"%%{k}%%", str(v))
    return page


def main(argv=None):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser(prog="dirxray", description="X-ray any folder. Zero installs.")
    ap.add_argument("path", nargs="?", default=".", help="folder to scan (default: .)")
    ap.add_argument("--html", metavar="FILE", help="write a self-contained HTML report")
    ap.add_argument("--json", action="store_true", help="print machine-readable JSON")
    ap.add_argument("--open", action="store_true", help="open the HTML report in your browser")
    ap.add_argument("--top", type=int, default=8, help="rows per section in the terminal (default 8)")
    ap.add_argument("--fail-under", type=int, metavar="SCORE", help="exit 1 if health score is lower (CI)")
    ap.add_argument("--version", action="version", version=f"dirxray {__version__}")
    a = ap.parse_args(argv)

    if not os.path.isdir(a.path):
        sys.exit(f"dirxray: not a folder: {a.path}")
    r = scan(a.path)
    if a.json:
        print(json.dumps(r, indent=2))
    else:
        print_report(r, a.top)
    if a.open and not a.html:
        a.html = "xray.html"
    if a.html:
        with open(a.html, "w", encoding="utf-8") as f:
            f.write(render_html(r))
        print(f"HTML report saved -> {a.html}", file=sys.stderr if a.json else sys.stdout)
        if a.open:
            webbrowser.open("file://" + os.path.abspath(a.html))
    if a.fail_under is not None and r["score"] < a.fail_under:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
