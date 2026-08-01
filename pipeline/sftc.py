"""서울시 상가임대차 실태조사 — published goodwill (권리금) as an external control.

Contract: docs/tracking/criteria-goodwill-survey-benchmark.md

`service/goodwill.py` produces an estimate, a band and a sensitivity table, all
of which come out of the same formula. Nothing outside that formula has ever
checked it. The Seoul survey publishes goodwill actually paid, by commercial
district and (in some editions) by industry, so it can serve as the first
external control the valuation has had.

Four measured facts shape this module.

**The reports are images.** `pdftotext -layout` yields 280 bytes for the 44-page
2023 edition and 78 bytes for the 78-page 2022 edition — one form-feed per page
and nothing else. Every page is a single JPEG. A vision model is not a
preference here, it is the only route. 80 dpi is already legible; the extra dpi
in EXTRACT_DPI buys digit accuracy, not readability.

**The document prints its own checksums.** The district table prints
「초기투자비 = 보증금 + 권리금 + 시설투자비」 and carries the total column, so a
row that was misread almost always fails to add up (2023 sample: 7/7 exact). The
industry table's six bands must sum to 100. Extraction is therefore gated on
arithmetic that came from the source, not on the model's confidence. Rows that
fail are dropped and reported — never repaired, because a repaired row is
indistinguishable from a correct one downstream.

**Page numbers cannot be hardcoded.** The 2022 edition has an 업종별 분석
section with a goodwill table on p.57; the 2023 edition dropped that section
entirely and moved the district table. Editions are not a stable layout, so the
pages are located by looking at the document.

**The board needs a session.** `NR_view.do` returns 200 and a content-free shell
without a cookie from the list page; with one it returns the post and its
attachment UUID. Downloads live under /common/file/, not /fe/bbs/.
"""
import argparse
import base64
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import requests

from .config import CACHE_DIR, load_env

BASE = "https://sftc.seoul.go.kr"
LIST_URL = f"{BASE}/fe/bbs/NR_list.do"
VIEW_URL = f"{BASE}/fe/bbs/NR_view.do"
BOARD = {"bbsCd": "2", "ctgCd": "4"}          # 자료실 > 상가임대차
UA = "Mozilla/5.0 (compatible; KB-Previl/1.0)"

DIR = CACHE_DIR / "sftc"

LOCATE_DPI = 100        # enough to read column headers and row labels verbatim
LOCATE_BATCH = 4

# The embedded page images are 220 ppi (measured, `pdfimages -list`), so
# rendering above that interpolates and adds nothing.
EXTRACT_DPI = 220

# A full page of this table is ~66 rows across three side-by-side blocks. Sent
# whole, two independent reads of 2023 p.27 agreed on 21 of 77 rows; the vision
# API downsamples a large image, and a dense numeric table does not survive it.
# Slicing the page into its blocks keeps every row near native resolution.
# The overlap is there so a slice boundary cannot cut a row out of both slices;
# rows seen twice with identical values are merged, not dropped.
EXTRACT_SLICES = 3
SLICE_OVERLAP = 0.04
VISION_MODEL = "gpt-5.4-mini"

# Rounding slack. The district table is printed in 만원 and the 2023 sample added
# up exactly; ±1 covers editions that round each column independently. The
# industry table's bands are printed to one decimal, so six of them can drift.
TRDAR_TOL = 1.0
UPTAE_TOL = 0.3

TABLES = ("trdar", "uptae")

# The survey's industry classes are KSIC sub-groups, which map cleanly onto the
# Seoul commercial-analysis food codes in config.FOOD_INDUTY. This is a
# correspondence between two standard taxonomies, not a judgement call:
#   5611 한식 / 5612 외국식 / 5619 기타 간이 / 562 주점·비알코올
SURVEY_UPTAE_TO_INDUTY = {
    "한식음식점": ["CS100001"],
    "외국식음식점": ["CS100002", "CS100003", "CS100004"],
    "간이음식점": ["CS100005", "CS100006", "CS100007", "CS100008"],
    "주점/비알코올음료": ["CS100009", "CS100010"],
}


class SftcError(RuntimeError):
    """A required source or tool is unavailable. Never caught to substitute a
    default — a missing control is reported, not imputed."""


# --------------------------------------------------------------- discovery

def _session():
    s = requests.Session()
    s.headers["User-Agent"] = UA
    # The list page is what mints the session the detail page requires.
    r = s.get(LIST_URL, params={**BOARD, "rowPerPage": "50"}, timeout=30)
    r.raise_for_status()
    return s, r.text


_SEQ = re.compile(r"BBS\.view\('(\d+)'\)")
_TITLE = re.compile(r'title="([^"]*)"')

# The board writes the survey year three ways across four posts: 2023년, '23년,
# 22년. Four-digit wins where present; the two-digit form is only consulted when
# there is no four-digit year, so "2015" never degrades into "15".
_YEAR4 = re.compile(r"(20\d{2})\s*년")
_YEAR2 = re.compile(r"['’]?([12]\d)\s*년")


def _year_of(*texts):
    """Prefer the attachment filename over the post title — the title may name
    two editions ("2015 및 2017년") while the file is one of them, and mislabelling
    which report a PDF is would silently attribute one year's numbers to another.
    """
    for t in texts:
        if not t:
            continue
        m = _YEAR4.search(t)
        if m:
            return int(m.group(1))
        m = _YEAR2.search(t)
        if m:
            return 2000 + int(m.group(1))
    return None


def _titles(html):
    """(bbsSeq, title) in board order. The title sits in the anchor's own
    attribute, so it survives the markup changing around it."""
    out = []
    for m in _SEQ.finditer(html):
        tail = html[m.end():m.end() + 400]
        t = _TITLE.search(tail)
        out.append((m.group(1), (t.group(1) if t else "").strip()))
    return out


_DOWNLOAD = re.compile(r"/common/file/NR_download\.do\?id=([0-9a-f-]{36})")
_FILENAME = re.compile(r"title='([^']*\.pdf)'")


def _attachment(session, seq):
    r = session.get(
        VIEW_URL,
        params={**BOARD, "bbsSeq": seq, "searchVal": "",
                "currentPage": "1", "rowPerPage": "10"},
        headers={"Referer": f"{LIST_URL}?bbsCd=2&ctgCd=4"},
        timeout=30,
    )
    r.raise_for_status()
    uid = _DOWNLOAD.search(r.text)
    name = _FILENAME.search(r.text)
    return (uid.group(1) if uid else None, name.group(1) if name else None)


def discover(verbose=True):
    """Board -> survey reports with their attachment UUIDs.

    Kept to titles containing 실태조사 so the board's guides, cardnews and
    notices do not enter the set. The survey year comes from the title, which is
    the only place it appears — the posting date is a year later.
    """
    session, html = _session()
    found = []
    for seq, title in _titles(html):
        if "실태조사" not in title:
            continue
        uid, name = _attachment(session, seq)
        if uid is None:
            if verbose:
                print(f"  [건너뜀] seq={seq} 첨부 없음 — {title[:40]}")
            continue
        found.append({"seq": seq, "year": _year_of(name, title),
                      "title": title, "id": uid, "filename": name})
    if verbose:
        print(f"실태조사 보고서 {len(found)}건")
        for f in found:
            print(f"  {f['year'] or '????'}  seq={f['seq']}  {f['id']}  "
                  f"{(f['filename'] or f['title'])[:52]}")
    if not found:
        raise SftcError("게시판에서 실태조사 보고서를 찾지 못했다 — 목록 구조가 바뀌었을 수 있다")
    DIR.mkdir(parents=True, exist_ok=True)
    (DIR / "index.json").write_text(
        json.dumps(found, ensure_ascii=False, indent=2), encoding="utf-8")
    return found


# ------------------------------------------------------------------- fetch

def _index():
    p = DIR / "index.json"
    if not p.is_file():
        raise SftcError("index.json 없음 — 먼저 --discover 를 돌릴 것")
    return json.loads(p.read_text(encoding="utf-8"))


def pdf_path(year):
    return DIR / f"sftc-{year}.pdf"


def fetch(year=None, verbose=True):
    """Download the report PDFs. Cached by year; the hash is printed so a
    silently republished source shows up as a changed digest."""
    session, _ = _session()
    out = []
    for entry in _index():
        if entry["year"] is None or (year and entry["year"] != year):
            continue
        dst = pdf_path(entry["year"])
        if dst.is_file():
            state = "cached"
        else:
            r = session.get(f"{BASE}/common/file/NR_download.do",
                            params={"id": entry["id"]}, timeout=180)
            r.raise_for_status()
            if not r.content.startswith(b"%PDF"):
                raise SftcError(
                    f"{entry['year']}년 다운로드가 PDF 가 아니다 "
                    f"({len(r.content)}바이트) — 세션이 끊겼을 수 있다")
            tmp = dst.with_suffix(".part")
            tmp.write_bytes(r.content)
            tmp.replace(dst)
            state = "downloaded"
        digest = hashlib.sha256(dst.read_bytes()).hexdigest()
        out.append({"year": entry["year"], "path": str(dst),
                    "bytes": dst.stat().st_size, "sha256": digest,
                    "state": state})
        if verbose:
            print(f"  {entry['year']}  {state:<10} {dst.stat().st_size:>10,}B  "
                  f"sha256:{digest[:12]}")
    if not out:
        raise SftcError("받을 대상이 없다")
    return out


# ------------------------------------------------------------------ render

def _require(tool):
    if shutil.which(tool) is None:
        raise SftcError(f"{tool} 없음 — poppler 를 설치할 것 (winget: oschwartz10612.Poppler)")


def page_count(path):
    _require("pdfinfo")
    # Bytes, not text=True: these PDFs carry Korean metadata and the Windows
    # locale codec (cp949) raises on it, which would take out the whole run over
    # a field nothing here reads.
    r = subprocess.run(["pdfinfo", str(path)], capture_output=True, timeout=120)
    m = re.search(r"^Pages:\s+(\d+)", r.stdout.decode("utf-8", "replace"), re.M)
    if not m:
        raise SftcError(f"페이지 수를 읽지 못했다: {path}")
    return int(m.group(1))


def _page_px(path, dpi):
    """Rendered page size in pixels — pdftoppm's crop flags are pixel units."""
    r = subprocess.run(["pdfinfo", str(path)], capture_output=True, timeout=120)
    m = re.search(r"^Page size:\s+([\d.]+) x ([\d.]+) pts",
                  r.stdout.decode("utf-8", "replace"), re.M)
    if not m:
        raise SftcError("페이지 크기를 읽지 못했다")
    w, h = float(m.group(1)), float(m.group(2))
    return round(w / 72 * dpi), round(h / 72 * dpi)


def render_slices(path, page, dpi, out_dir, n=EXTRACT_SLICES,
                  overlap=SLICE_OVERLAP):
    """Render one page as `n` vertical strips, cropped by poppler itself so no
    image library is needed."""
    _require("pdftoppm")
    width, height = _page_px(path, dpi)
    step = width / n
    pad = round(step * overlap)
    out = []
    for i in range(n):
        x = max(0, round(i * step) - pad)
        w = min(width - x, round(step) + 2 * pad)
        prefix = out_dir / f"s{i}"
        subprocess.run(["pdftoppm", "-png", "-r", str(dpi),
                        "-f", str(page), "-l", str(page),
                        "-x", str(x), "-y", "0", "-W", str(w), "-H", str(height),
                        str(path), str(prefix)],
                       check=True, capture_output=True, timeout=900)
        got = sorted(out_dir.glob(f"s{i}-*.png"))
        if not got:
            raise SftcError(f"p{page} 슬라이스 {i} 렌더 실패")
        out.append(got[0])
    return out


def render(path, first, last, dpi, out_dir):
    _require("pdftoppm")
    prefix = out_dir / "p"
    subprocess.run(["pdftoppm", "-png", "-r", str(dpi),
                    "-f", str(first), "-l", str(last), str(path), str(prefix)],
                   check=True, capture_output=True, timeout=900)
    pages = {}
    for f in sorted(out_dir.glob("p-*.png")):
        pages[int(f.stem.split("-")[-1])] = f
    return pages


# ------------------------------------------------------------------ vision

def _client():
    key = load_env().get("OPENAI_API_KEY")
    if not key:
        raise SftcError("OPENAI_API_KEY 없음 — 이미지 PDF 는 비전 모델 외에 경로가 없다")
    from openai import OpenAI
    return OpenAI(api_key=key)


def _image_part(path):
    b64 = base64.b64encode(path.read_bytes()).decode()
    return {"type": "image_url",
            "image_url": {"url": f"data:image/png;base64,{b64}"}}


def _ask(client, parts, instruction):
    r = client.chat.completions.create(
        model=VISION_MODEL,
        response_format={"type": "json_object"},
        messages=[{"role": "user",
                   "content": [{"type": "text", "text": instruction}] + parts}],
    )
    return json.loads(r.choices[0].message.content)


# Asking the model to *classify* the table failed in practice: given eight
# thumbnails it labelled the district table "uptae" and, on a second run,
# returned null for every page including ones that plainly have a 권리금 column.
# Transcription is what vision models are reliable at, so the model now only
# copies the printed headers and row labels, and the classification below is
# ordinary Python over that evidence.
LOCATE_PROMPT = """\
각 이미지는 「서울시 상가임대차 실태조사」 보고서의 한 페이지다.
판단하지 말고 **보이는 글자를 그대로 옮겨라.**

각 페이지마다:
- title: 표 바로 위에 붙은 제목/캡션. 없으면 "".
- headers: 데이터 표의 컬럼 머리글을 인쇄된 순서대로. 병합된 상위 머리글이
  있으면 그것도 포함하라. 표가 없으면 [].
- labels: 그 표의 첫 세 데이터 행에서 맨 왼쪽 칸의 이름. 없으면 [].

표가 좌우 여러 블록으로 반복되면 첫 블록만 보면 된다.

JSON 으로만 답하라:
{"pages": [{"page": <번호>, "title": "...", "headers": [...], "labels": [...]}]}
입력된 이미지 개수만큼, 주어진 페이지 번호를 그대로 써서 반환하라.
페이지 번호(순서대로): %s
"""

# Row labels decide the table kind. The survey's industry classes are KSIC
# names and every one of them carries one of these words; commercial-district
# names (가로수길, 강남역, 홍대입구역) carry none.
_UPTAE_LABEL = re.compile(r"음식점|주점|비알코올|판매|서비스업|숙박|도소매|의약품")


def classify(headers, labels, title=""):
    """Table kind from transcribed text alone, or None if this is not a
    goodwill table.

    The title has to count, not just the headers: the district table names
    권리금 as a column, but the industry table's columns are money bands
    (「2천만원 미만」…「평균」) and 권리금 appears only in the caption
    「업종별 권리금」. Checking headers alone would never find that page.
    """
    seen = list(headers or []) + [title or ""]
    if not any("권리금" in str(s) for s in seen):
        return None
    for lab in labels or []:
        if _UPTAE_LABEL.search(str(lab)):
            return "uptae"
    return "trdar"


def locate(year, table=None, verbose=True):
    """Find the pages carrying a goodwill column. Deliberately not a constant:
    the 2022 edition puts the industry table on p.57 and the 2023 edition has no
    industry table at all."""
    path = pdf_path(year)
    if not path.is_file():
        raise SftcError(f"{year}년 PDF 없음 — 먼저 --fetch")
    client = _client()
    n = page_count(path)
    hits = []
    tmp = Path(tempfile.mkdtemp(prefix="sftc-locate-", dir=str(DIR)))
    try:
        for start in range(1, n + 1, LOCATE_BATCH):
            end = min(start + LOCATE_BATCH - 1, n)
            batch = Path(tempfile.mkdtemp(dir=str(tmp)))
            pages = render(path, start, end, LOCATE_DPI, batch)
            nums = sorted(pages)
            parts = [_image_part(pages[i]) for i in nums]
            ans = _ask(client, parts, LOCATE_PROMPT % nums)
            for row in ans.get("pages", []):
                kind = classify(row.get("headers"), row.get("labels"),
                                row.get("title", ""))
                if kind:
                    hits.append({"page": int(row["page"]), "table": kind,
                                 "title": row.get("title", ""),
                                 "headers": row.get("headers"),
                                 "labels": row.get("labels")})
            if verbose:
                print(f"  p{start}-{end} 검사 … 누적 {len(hits)}면")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    hits.sort(key=lambda h: h["page"])
    # The full sweep is what gets cached. Filtering before the write would let
    # `--locate 2023 --table uptae` (a legitimate "is it in here?" question)
    # erase the district pages that --extract needs.
    (DIR / f"locate-{year}.json").write_text(
        json.dumps(hits, ensure_ascii=False, indent=2), encoding="utf-8")

    shown = [h for h in hits if h["table"] == table] if table else hits
    if verbose:
        if shown:
            for kind in TABLES:
                pp = [h["page"] for h in shown if h["table"] == kind]
                if pp:
                    print(f"  {kind}: p{', p'.join(map(str, pp))}")
        else:
            what = {"trdar": "상권별 ", "uptae": "업종별 "}.get(table, "")
            print(f"  이 판에는 {what}권리금 표가 없다 — {year}년판 {n}면 전부 검사함")
    return shown


TRDAR_PROMPT = """\
이 이미지는 「서울시 상가임대차 실태조사」 상권별 초기투자비 표의 **한 세로 블록**이다.
표에 인쇄된 모든 데이터 행을 읽어라. 단위는 만원이고 값에 쉼표가 있다.

각 행: 상권명, 계, 보증금, 권리금, 시설투자비.
자치구(구역) 열은 여러 행에 걸쳐 병합돼 있을 수 있다 — 각 행에 해당 자치구를 채워라.
가장자리에서 잘린 행은 건너뛰어라.
합계/평균 행은 제외하고 개별 상권 행만 반환하라.
**값을 보정하거나 계산해서 채우지 말고 인쇄된 숫자를 그대로 읽어라.
보이지 않는 행을 추측해서 만들지 마라.**

JSON: {"rows": [{"gu": "강남구", "trdar": "가로수길", "total": 25595,
                 "deposit": 10257, "goodwill": 10225, "fitout": 5113}]}
"""

UPTAE_PROMPT = """\
이 이미지는 「서울시 상가임대차 실태조사」의 업종별 권리금 표다.
표에 인쇄된 모든 데이터 행을 읽어라.

각 행: 업종명, 권리금 구간별 비율 6개(%), 평균(만원).
구간은 인쇄된 순서 그대로다 (2천만원 미만 → 1억원 이상).
「계」 행도 포함하라.
**값을 보정하지 말고 인쇄된 숫자를 그대로 읽어라.**

JSON: {"rows": [{"uptae": "한식음식점",
                 "bands": [23.2, 22.1, 21.2, 10.1, 5.2, 18.2],
                 "mean": 6165.4}]}
"""


def _key(row, table):
    if table == "trdar":
        return (str(row.get("gu", "")).strip(), str(row.get("trdar", "")).strip())
    return (str(row.get("uptae", "")).strip(),)


def _values(row, table):
    fields = (("total", "deposit", "goodwill", "fitout") if table == "trdar"
              else ("mean",))
    out = []
    for f in fields:
        try:
            out.append(round(float(row[f]), 3))
        except (KeyError, TypeError, ValueError):
            return None
    if table == "uptae":
        try:
            out.extend(round(float(b), 3) for b in row["bands"])
        except (KeyError, TypeError, ValueError):
            return None
    return tuple(out)


def agree(runs, table):
    """Keep only rows that two independent reads of the same image produced
    identically.

    The printed checksum catches a misread digit, but it cannot catch a row the
    model invented — measured on the 2023 edition, p.27 produced rows belonging
    to districts that are not on that page, and those rows added up correctly
    because the model made them add up. What fabrication cannot do is repeat
    itself verbatim, so agreement across passes is the check that separates a
    transcription from a plausible construction.
    """
    seen = [{_key(r, table): (r, _values(r, table)) for r in run} for run in runs]
    first = seen[0]
    stable, unstable = [], []
    for key, (row, vals) in first.items():
        others = [s.get(key) for s in seen[1:]]
        if vals is not None and all(o and o[1] == vals for o in others):
            stable.append(row)
        else:
            missing = any(o is None for o in others)
            unstable.append({**row, "reason": ("재추출에 없음" if missing
                                               else "재추출과 값 불일치")})
    for s in seen[1:]:
        for key, (row, _) in s.items():
            if key not in first:
                unstable.append({**row, "reason": "1차 추출에 없음"})
    return stable, unstable


def extract(year, table, passes=2, verbose=True):
    """Read the located pages at EXTRACT_DPI, twice, and keep only rows that
    both passes agree on AND that satisfy the checksum the document prints.

    Output is a JSON artefact — the vision call is the expensive,
    non-deterministic step and must not be part of loading.
    """
    hits = [h for h in _locate_cache(year) if h["table"] == table]
    if not hits:
        raise SftcError(f"{year}년판에 {table} 표가 없다 — --locate 결과가 비었다")
    path = pdf_path(year)
    client = _client()
    prompt = TRDAR_PROMPT if table == "trdar" else UPTAE_PROMPT
    rows, unstable = [], []
    tmp = Path(tempfile.mkdtemp(prefix="sftc-extract-", dir=str(DIR)))
    try:
        # The industry table is a single narrow block; slicing it would cut rows.
        slices = EXTRACT_SLICES if table == "trdar" else 1
        for hit in hits:
            page = hit["page"]
            work = Path(tempfile.mkdtemp(dir=str(tmp)))
            if slices > 1:
                images = render_slices(path, page, EXTRACT_DPI, work, slices)
            else:
                images = [render(path, page, page, EXTRACT_DPI, work)[page]]
            page_stable, page_drift = [], []
            for si, img in enumerate(images):
                part = _image_part(img)
                runs = []
                for _ in range(passes):
                    got = _ask(client, [part], prompt).get("rows", [])
                    for r in got:
                        r["page"] = page
                        r["slice"] = si
                    runs.append(got)
                s, d = agree(runs, table)
                page_stable.extend(s)
                page_drift.extend(d)
            rows.extend(page_stable)
            unstable.extend(page_drift)
            if verbose:
                total = len(page_stable) + len(page_drift)
                print(f"  p{page} ({len(images)}블록) … 후보 {total}행 → "
                      f"일치 {len(page_stable)} · 불일치 {len(page_drift)}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    accepted, rejected = verify_rows(rows, table)
    accepted, duplicated = _dedupe(accepted, table)
    payload = {"year": year, "table": table, "pages": [h["page"] for h in hits],
               "passes": passes, "accepted": accepted, "rejected": rejected,
               "unstable": unstable, "duplicated": duplicated}
    out = DIR / f"sftc-{year}-{table}.json"
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    if verbose:
        _report(accepted, rejected, unstable, duplicated, table)
        print(f"  -> {out.name}")
    return payload


def _locate_cache(year):
    p = DIR / f"locate-{year}.json"
    if not p.is_file():
        raise SftcError(f"locate-{year}.json 없음 — 먼저 --locate {year}")
    return json.loads(p.read_text(encoding="utf-8"))


# ------------------------------------------------------------------ verify

def verify_rows(rows, table):
    """Split rows on the checksum printed in the source document.

    A failing row is never repaired. The total column is what makes the check
    work: a misread digit has to be matched by three other misreads in exactly
    the right direction to still add up, so passing rows carry real evidence and
    a repaired row would carry none.
    """
    accepted, rejected = [], []
    for r in rows:
        try:
            if table == "trdar":
                parts = [float(r["deposit"]), float(r["goodwill"]), float(r["fitout"])]
                total = float(r["total"])
                delta = sum(parts) - total
                ok = abs(delta) <= TRDAR_TOL
            else:
                bands = [float(b) for b in r["bands"]]
                delta = sum(bands) - 100.0
                ok = len(bands) == 6 and abs(delta) <= UPTAE_TOL
        except (KeyError, TypeError, ValueError) as exc:
            rejected.append({**r, "reason": f"필드 결손/형식 오류: {type(exc).__name__}"})
            continue
        if ok:
            accepted.append({**r, "checksum_delta": round(delta, 3)})
        else:
            rejected.append({**r, "reason": f"검산 불일치 {delta:+.2f}"})
    return accepted, rejected


def _name(row):
    return str(row.get("trdar") or row.get("uptae") or "").strip()


def _dedupe(rows, table):
    """A district (or industry) may appear once in the table.

    Two copies mean one of two different things. Byte-identical copies are the
    slice overlap seeing the same printed row twice — corroboration, merged to
    one. Copies that disagree on any field mean one of them is wrong and nothing
    in the data says which, so every copy is dropped and named; picking one
    would put an unverifiable row into a control set.
    """
    groups = {}
    for r in rows:
        groups.setdefault(_name(r), []).append(r)
    kept, dupes = [], []
    for name, g in groups.items():
        if len(g) == 1:
            kept.append(g[0])
            continue
        sig = {(_key(r, table), _values(r, table)) for r in g}
        if len(sig) == 1:
            kept.append(g[0])
        else:
            dupes.extend({**r, "reason": f"이름 중복 {len(g)}건 · 값 불일치"}
                         for r in g)
    return kept, dupes


def _report(accepted, rejected, unstable, duplicated, table):
    n = len(accepted) + len(rejected) + len(unstable) + len(duplicated)
    check = ("계 = 보증금+권리금+시설투자비" if table == "trdar"
             else "구간 백분율 합 = 100")
    print(f"  채택 {len(accepted)}행 / 후보 {n}행")
    print(f"    재추출 불일치 {len(unstable)} · 검산({check}) 탈락 "
          f"{len(rejected)} · 이름 중복 {len(duplicated)}")
    for r in (rejected + duplicated)[:8]:
        print(f"    [탈락] p{r.get('page','?')} {_name(r)} — {r['reason']}")
    if len(rejected) + len(duplicated) > 8:
        print(f"    … 외 {len(rejected)+len(duplicated)-8}행")


# ------------------------------------------------------------------ compare

SAMPLE_PER_UPTAE = 150
SAMPLE_SEED = 0
# Any value at or above the survival curve's horizon leaves N decided by the
# grade curve rather than by an arbitrary lease assumption.
LEASE_YEARS = 5.0


def _spearman(a, b):
    """Rank correlation for a handful of points. No scipy — this runs on four
    industries and importing a stack for it would be its own liability."""
    n = len(a)
    if n < 2:
        return None
    ra = {v: i for i, v in enumerate(sorted(a))}
    rb = {v: i for i, v in enumerate(sorted(b))}
    d2 = sum((ra[x] - rb[y]) ** 2 for x, y in zip(a, b))
    return 1 - 6 * d2 / (n * (n * n - 1))


# 「2천만원 미만 | 2천~4천 | 4천~6천 | 6천~8천 | 8천~1억 | 1억 이상」, 단위 만원.
BAND_EDGES = (0, 2000, 4000, 6000, 8000, 10000, None)


def median_from_bands(bands):
    """Median of the published distribution by linear interpolation inside the
    band that crosses 50%.

    The published headline is a mean, and goodwill is right-tailed — the 2022
    한식 mean is 6,165 while its median lands near 4,400. Comparing our median
    against their mean would charge the estimate for a skew it never claimed to
    model. Returns None if the median falls in the open-ended top band, where
    interpolation would be invention.
    """
    cum = 0.0
    for i, b in enumerate(bands):
        b = float(b)
        if cum + b >= 50.0:
            lo, hi = BAND_EDGES[i], BAND_EDGES[i + 1]
            if hi is None or b <= 0:
                return None
            return lo + (50.0 - cum) / b * (hi - lo)
        cum += b
    return None


def _quantile(sorted_vals, q):
    if not sorted_vals:
        return None
    i = min(len(sorted_vals) - 1, max(0, int(round(q * (len(sorted_vals) - 1)))))
    return sorted_vals[i]


def _sample_grids(con, n, seed):
    import random
    ids = [r[0] for r in con.execute(
        "SELECT grid_id FROM grid_feature WHERE has_sales_data = 1 "
        "ORDER BY grid_id")]
    rng = random.Random(seed)
    return ids if len(ids) <= n else rng.sample(ids, n)


def compare(year=2022, sample=SAMPLE_PER_UPTAE, verbose=True):
    """Our intangible estimate against the published goodwill, by industry.

    Read-only. Runs `service.goodwill` exactly as the product does — asking
    price and tangible assets are user inputs that do not enter the estimate,
    so they are left at their empty values rather than invented.
    """
    from pipeline.config import UPTAE_INDUTY
    from service import api
    from service import goodwill as gw

    path = DIR / f"sftc-{year}-uptae.json"
    if not path.is_file():
        raise SftcError(f"{path.name} 없음 — 먼저 --extract {year} --table uptae")
    survey = {r["uptae"].replace(" ", ""): r
              for r in json.loads(path.read_text(encoding="utf-8"))["accepted"]}

    with api.base.readonly_connection() as con:
        grids = _sample_grids(con, sample, SAMPLE_SEED)

    rows = []
    for survey_name, codes in SURVEY_UPTAE_TO_INDUTY.items():
        ours = [u for u, c in UPTAE_INDUTY.items() if c in codes]
        vals, unavailable = [], 0
        for uptae in ours:
            for gid in grids:
                try:
                    r = gw.calculate_from_sources(
                        grid_id=gid, uptae=uptae, asking_goodwill=0,
                        lease_remaining_years=LEASE_YEARS, assets=[])
                except (gw.GoodwillUnavailableError, api.ApiInputError,
                        api.ResourceNotFoundError):
                    unavailable += 1
                    continue
                vals.append(r["intangible_value"])
        key = survey_name.replace(" ", "")
        pub = survey.get(key)
        allv = sorted(vals)
        nonzero = sorted(v for v in vals if v > 0)
        rows.append({
            "survey_uptae": survey_name,
            "our_uptae": ours,
            "n": len(vals),
            "unavailable": unavailable,
            "nonzero_rate": (len(nonzero) / len(vals)) if vals else None,
            "our_median_nonzero": _quantile(nonzero, 0.5),
            # Prediction 3 said the two denominators differ, so the like-for-like
            # reading is our top 26.5% — the same share of locations that the
            # survey observed paying anything at all.
            "our_median_top_payers": _quantile(
                allv, 1.0 - SURVEY_PAYER_RATE / 2),
            "published_mean": (pub["mean"] if pub else None),
            "published_median": (median_from_bands(pub["bands"]) if pub else None),
        })

    if verbose:
        _compare_report(rows, survey)
    (DIR / f"compare-{year}.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    return rows


# Measured in the same edition (2022 p.58): 3,258 of 12,296 surveyed shops paid
# goodwill. The published averages are conditional on paying, so our unconditional
# estimates are not on the same footing and the report has to say so.
SURVEY_PAYER_RATE = 0.265


def _compare_report(rows, survey):
    print(f"\n업종별 대조 (표본 {SAMPLE_PER_UPTAE}격자/업태 · "
          f"임대차 잔여 {LEASE_YEARS:.0f}년)")
    print(f"{'업종':<14}{'표본':>6}{'비영':>7}"
          f"{'우리 중앙':>10}{'공표 중앙':>10}{'배율':>7}"
          f"{'분모맞춤':>10}{'배율':>7}")
    ours, pubs = [], []
    for r in rows:
        med, pmed = r["our_median_nonzero"], r["published_median"]
        top = r["our_median_top_payers"]
        f1 = f"{med/pmed:.2f}x" if (med and pmed) else "—"
        f2 = f"{top/pmed:.2f}x" if (top and pmed) else "—"
        print(f"{r['survey_uptae']:<14}{r['n']:>6,}"
              f"{(r['nonzero_rate'] or 0)*100:>6.1f}%"
              f"{(med or 0):>10,.0f}{(pmed or 0):>10,.0f}{f1:>7}"
              f"{(top or 0):>10,.0f}{f2:>7}")
        if med and pmed:
            ours.append(med)
            pubs.append(pmed)
    rho = _spearman(ours, pubs)
    print(f"\n  순위상관(우리 ↔ 공표 중앙값) rho = "
          f"{'%.3f' % rho if rho is not None else '—'}  (n={len(ours)})")
    print("  공표 중앙값은 구간분포에서 보간 — 헤드라인 평균은 우측 꼬리에 끌린다")
    print(f"  공표 분모 = 권리금 지불자 {SURVEY_PAYER_RATE*100:.1f}% "
          f"(2022 p.58: 3,258/12,296호) · «분모맞춤» = 우리 상위 {SURVEY_PAYER_RATE*100:.1f}%의 중앙값")


# --------------------------------------------------------------------- cli

def main():
    ap = argparse.ArgumentParser(
        description="서울시 상가임대차 실태조사 권리금 수집·추출·검정")
    ap.add_argument("--discover", action="store_true", help="게시판에서 보고서 목록 발견")
    ap.add_argument("--fetch", action="store_true", help="PDF 다운로드(캐시)")
    ap.add_argument("--locate", type=int, metavar="YEAR", help="권리금 표 페이지 탐색")
    ap.add_argument("--extract", type=int, metavar="YEAR", help="표 추출 + 검산")
    ap.add_argument("--table", choices=TABLES, help="trdar(상권별) / uptae(업종별)")
    ap.add_argument("--year", type=int, help="--fetch 대상 연도")
    ap.add_argument("--compare", action="store_true",
                    help="우리 추정가 분포 vs 공표 권리금 (읽기 전용)")
    a = ap.parse_args()

    try:
        if a.discover:
            discover()
        if a.fetch:
            fetch(a.year)
        if a.locate:
            locate(a.locate, a.table)
        if a.extract:
            if not a.table:
                ap.error("--extract 는 --table 이 필요하다")
            extract(a.extract, a.table)
        if a.compare:
            compare()
        if not any([a.discover, a.fetch, a.locate, a.extract, a.compare]):
            ap.print_help()
    except SftcError as exc:
        print(f"실패: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
