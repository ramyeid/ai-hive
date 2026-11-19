#!/usr/bin/env python3
"""Files the lead attaches in a chat (data/uploads/), as text an agent can read.

    python3 files.py read <file> [--rows N] [--sheet NAME]
        .xlsx / .xlsm   every sheet as a Markdown table (first 200 rows each unless --rows; --sheet for one)
        .csv / .tsv     the same, as one table
        .docx           the text, headings and tables
        .pptx           each slide's text
        .pdf            the text, with pdftotext when it's installed (otherwise read the PDF with your Read tool)
        text files      as they are
    python3 files.py list                     the files attached so far, newest first

Images: look at them with your Read tool. Standard library only.
"""
from __future__ import annotations

import csv
import datetime as dt
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parent))
from tasklib import DATA  # noqa: E402

UPLOADS = DATA / "uploads"
NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
      "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
      "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
      "a": "http://schemas.openxmlformats.org/drawingml/2006/main"}
REL = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
DATE_FORMATS = {14, 15, 16, 17, 22, 27, 30, 36, 45, 46, 47, 50, 57}


def cell(value) -> str:
    return " ".join(str(value).split()).replace("|", "\\|")


def table(rows: list[list], limit: int) -> str:
    rows = [r for r in rows if any(str(c).strip() for c in r)]
    if not rows:
        return "(empty)"
    width = max(len(r) for r in rows)
    rows = [list(r) + [""] * (width - len(r)) for r in rows]
    # drop columns that are empty all the way down
    keep = [i for i in range(width) if any(str(r[i]).strip() for r in rows)]
    rows = [[r[i] for i in keep] for r in rows]
    head, body = rows[0], rows[1:]
    out = ["| " + " | ".join(cell(c) for c in head) + " |", "|" + "---|" * len(head)]
    out += ["| " + " | ".join(cell(c) for c in r) + " |" for r in body[:limit]]
    if len(body) > limit:
        out.append(f"\n… {len(body) - limit} more rows (read them with --rows {len(body)})")
    return "\n".join(out)


def col_index(ref: str) -> int:
    letters = re.match(r"[A-Z]+", ref).group(0)
    n = 0
    for ch in letters:
        n = n * 26 + ord(ch) - 64
    return n - 1


def xlsx(path: Path, limit: int, only: str | None) -> str:
    z = zipfile.ZipFile(path)
    names = set(z.namelist())
    shared: list[str] = []
    if "xl/sharedStrings.xml" in names:
        for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall("m:si", NS):
            shared.append("".join(t.text or "" for t in si.iter(f"{{{NS['m']}}}t")))
    date_styles: set[int] = set()
    if "xl/styles.xml" in names:
        styles = ET.fromstring(z.read("xl/styles.xml"))
        custom = {int(f.get("numFmtId")) for f in styles.findall("m:numFmts/m:numFmt", NS)
                  if re.search(r"[dy]", (f.get("formatCode") or "").lower().replace("[red]", ""))}
        xfs = styles.find("m:cellXfs", NS)
        for i, xf in enumerate(xfs if xfs is not None else []):
            fid = int(xf.get("numFmtId", 0))
            if fid in DATE_FORMATS or fid in custom:
                date_styles.add(i)
    book = ET.fromstring(z.read("xl/workbook.xml"))
    rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
    targets = {r.get("Id"): r.get("Target") for r in rels}
    parts = []
    sheets = book.findall("m:sheets/m:sheet", NS)
    if only and not any(s.get("name") == only for s in sheets):
        return f"No sheet called {only!r}. Sheets: " + ", ".join(s.get("name") for s in sheets)
    parts.append(f"{path.name}: {len(sheets)} sheet{'s' if len(sheets) != 1 else ''} ("
                 + ", ".join(s.get("name") for s in sheets) + ")")
    for s in sheets:
        if only and s.get("name") != only:
            continue
        target = targets[s.get(REL)].lstrip("/")
        target = target if target.startswith("xl/") else "xl/" + target
        root = ET.fromstring(z.read(target))
        rows: list[list] = []
        for row in root.iter(f"{{{NS['m']}}}row"):
            values: list = []
            for c in row.findall("m:c", NS):
                i = col_index(c.get("r")) if c.get("r") else len(values)
                while len(values) < i:
                    values.append("")
                kind, v, f = c.get("t"), c.find("m:v", NS), c.find("m:f", NS)
                text = (v.text or "") if v is not None else ""
                if not text and f is not None and f.text:   # a formula Excel never calculated
                    text, kind = f"={f.text}", "formula"
                if kind == "s" and text:
                    text = shared[int(text)]
                elif kind == "inlineStr":
                    text = "".join(t.text or "" for t in c.iter(f"{{{NS['m']}}}t"))
                elif kind == "b":
                    text = "TRUE" if text == "1" else "FALSE"
                elif text and int(c.get("s", 0)) in date_styles:
                    try:
                        d = dt.datetime(1899, 12, 30) + dt.timedelta(days=float(text))
                        text = d.strftime("%Y-%m-%d") if d.time() == dt.time() else d.strftime("%Y-%m-%d %H:%M")
                    except ValueError:
                        pass
                elif text and re.fullmatch(r"-?\d+\.\d{10,}", text):
                    text = f"{float(text):.6g}"
                values.append(text)
            rows.append(values)
        parts.append(f"\n## Sheet: {s.get('name')} ({len(rows)} rows)\n\n{table(rows, limit)}")
    return "\n".join(parts)


def delimited(path: Path, limit: int) -> str:
    raw = path.read_bytes()
    text = raw.decode("utf-8-sig", "replace")
    try:
        dialect = csv.Sniffer().sniff(text[:5000], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel_tab if path.suffix.lower() == ".tsv" else csv.excel
    rows = list(csv.reader(text.splitlines(), dialect))
    return f"{path.name}: {len(rows)} rows\n\n{table(rows, limit)}"


def docx(path: Path) -> str:
    root = ET.fromstring(zipfile.ZipFile(path).read("word/document.xml"))
    body = root.find("w:body", NS)
    out = []
    for block in body if body is not None else []:
        tag = block.tag.split("}")[1]
        if tag == "p":
            text = "".join(t.text or "" for t in block.iter(f"{{{NS['w']}}}t"))
            style = block.find("w:pPr/w:pStyle", NS)
            level = re.search(r"(\d)", style.get(f"{{{NS['w']}}}val", "")) if style is not None and "eading" in style.get(f"{{{NS['w']}}}val", "") else None
            if text.strip():
                out.append(("#" * int(level.group(1)) + " " if level else "") + text)
        elif tag == "tbl":
            rows = [["".join(t.text or "" for t in tc.iter(f"{{{NS['w']}}}t")) for tc in tr.findall("w:tc", NS)]
                    for tr in block.findall("w:tr", NS)]
            out.append(table(rows, 10_000))
    return "\n\n".join(out)


def pptx(path: Path) -> str:
    z = zipfile.ZipFile(path)
    slides = sorted((n for n in z.namelist() if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)),
                    key=lambda n: int(re.search(r"(\d+)", n).group(1)))
    out = []
    for i, name in enumerate(slides, 1):
        root = ET.fromstring(z.read(name))
        paras = ["".join(t.text or "" for t in p.iter(f"{{{NS['a']}}}t")) for p in root.iter(f"{{{NS['a']}}}p")]
        out.append(f"## Slide {i}\n" + "\n".join(p for p in paras if p.strip()))
    return "\n\n".join(out)


def pdf(path: Path) -> str:
    if shutil.which("pdftotext"):
        res = subprocess.run(["pdftotext", "-layout", str(path), "-"], capture_output=True, text=True, timeout=60)
        if res.returncode == 0 and res.stdout.strip():
            return res.stdout
    return (f"{path.name} is a PDF and pdftotext isn't installed (or found no text: a scan?). "
            f"Read it with your Read tool instead: {path}")


def read(path: Path, limit: int, sheet: str | None) -> str:
    if not path.exists():
        alt = UPLOADS / path
        if alt.exists():
            path = alt
        else:
            sys.exit(f"No such file: {path}")
    ext = path.suffix.lower()
    try:
        if ext in (".xlsx", ".xlsm"):
            return xlsx(path, limit, sheet)
        if ext in (".csv", ".tsv"):
            return delimited(path, limit)
        if ext == ".docx":
            return docx(path)
        if ext == ".pptx":
            return pptx(path)
    except (zipfile.BadZipFile, KeyError, ET.ParseError) as e:
        sys.exit(f"Couldn't read {path.name} as {ext}: {e}")
    if ext == ".pdf":
        return pdf(path)
    if ext in (".xls", ".doc", ".ppt"):
        sys.exit(f"{path.name} is the old Office format. Ask the lead to save it as {ext}x and attach it again.")
    if ext in (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"):
        return f"{path.name} is an image: look at it with your Read tool ({path})."
    data = path.read_bytes()
    if b"\0" in data[:4096]:
        sys.exit(f"{path.name} isn't a text file or a format this tool reads.")
    return data.decode("utf-8", "replace")


def main(argv: list[str]) -> int:
    if not argv or argv[0] not in ("read", "list"):
        print(__doc__)
        return 0 if not argv else 1
    if argv[0] == "list":
        files = sorted((p for p in UPLOADS.rglob("*") if p.is_file()), key=lambda p: p.stat().st_mtime, reverse=True)
        print("\n".join(f"{p}  ({p.stat().st_size // 1024 or 1} KB)" for p in files[:50]) or "Nothing attached yet.")
        return 0
    args = argv[1:]
    limit, sheet = 200, None
    if "--rows" in args:
        i = args.index("--rows"); limit = int(args[i + 1]); args = args[:i] + args[i + 2:]
    if "--sheet" in args:
        i = args.index("--sheet"); sheet = args[i + 1]; args = args[:i] + args[i + 2:]
    if not args:
        sys.exit("Usage: files.py read <file> [--rows N] [--sheet NAME]")
    print(read(Path(args[0]).expanduser(), limit, sheet))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
