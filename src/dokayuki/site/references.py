"""Build the site's reference list from references.bib, filtered by docs/REFERENCES_CHECK.md.

Only entries whose status is "yes" or "partial" (DOI and metadata verified; claim verified at least
from the abstract) are rendered. Anything else never reaches the page.
"""
from __future__ import annotations

import re
from pathlib import Path

from ..config import ROOT

ALLOWED = ("yes", "partial")


def parse_bib(path: Path) -> dict[str, dict]:
    text = path.read_text(encoding="utf-8")
    out = {}
    chunks = re.split(r"\n(?=@)", "\n" + text)
    for chunk in chunks:
        m = re.match(r"@(\w+)\{([^,]+),(.*)", chunk.strip(), flags=re.S)
        if not m:
            continue
        kind, key, body = m.group(1), m.group(2).strip(), m.group(3)
        fields = {}
        for fm in re.finditer(r"(\w+)\s*=\s*\{((?:[^{}]|\{[^{}]*\})*)\}", body, flags=re.S):
            fields[fm.group(1).lower()] = re.sub(r"\s+", " ", fm.group(2)).strip()
        fields["_kind"] = kind
        out[key] = fields
    return out


def verified_keys(check_md: Path) -> dict[str, str]:
    status = {}
    for line in check_md.read_text(encoding="utf-8").splitlines():
        if not line.startswith("| ") or line.startswith("| key") or line.startswith("|---"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) >= 5:
            status[cells[0]] = cells[4].lower()
    return status


def _authors(a: str) -> str:
    names = [n.strip() for n in a.split(" and ")]
    def short(n):
        return n.split(",")[0].strip() if "," in n else n.split()[-1]
    if len(names) == 1:
        return short(names[0])
    if len(names) == 2:
        return f"{short(names[0])} & {short(names[1])}"
    return f"{short(names[0])} et al."


def render(bib: Path = ROOT / "references.bib", check: Path = ROOT / "docs" / "REFERENCES_CHECK.md") -> list[dict]:
    entries = parse_bib(bib)
    status = verified_keys(check)
    out = []
    for key, f in entries.items():
        st = status.get(key, "unverified")
        if not any(st.startswith(a) for a in ALLOWED):
            continue
        venue = f.get("journal") or (f"arXiv:{f['eprint']}" if "eprint" in f else "")
        vol = f" {f['volume']}" if "volume" in f else ""
        pages = f", {f['pages'].replace('--', '–')}" if "pages" in f else ""
        text = f"{_authors(f.get('author', ''))} ({f.get('year', '')}). {f.get('title', '').replace('``', '“').replace(chr(39)+chr(39), '”')}. {venue}{vol}{pages}."
        out.append({"key": key, "text": text, "doi": f.get("doi"), "status": st})
    return out
