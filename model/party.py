"""방문객 동반자 표기 — 수집·추출·검정. 설계는 docs/unstructured-plan.md §J-1.

Different purpose, different bar. §I-20 and §I-23 were rejected at the 0.70
precision bar for *feature adoption*; this is a display label that never enters
the score, so §J-1 registers its own thresholds before this file runs.

Two design choices come straight from why `guest.party` was skipped in §19-B —
the judge attached labels 2.3x more often than an independent one:

**Quote or nothing.** Every label must carry the phrase from the text that
justifies it, 20 characters or less. An empty quote voids the label. This is the
same rule `absa_run` already uses, and it is the only thing stopping "feels like
a date" from becoming a data point.

**Abstention is a result.** No explicit mention means null, and the abstention
rate is reported. A classifier that must answer will invent an answer.

The hypothesis being tested is narrow: §19-A concluded that a 147-character
snippet cannot support a consistent judgement, and that held for 불만 7범주 and
for 목적 3클래스, both of which require *inferring* something. Companion type is
usually *stated* — 혼자, 남편이랑, 회식으로, 애들이랑. That is the only reason to
expect a different answer, and the pilot is sized to find out cheaply.

    python -m model.party --pilot      # 30 상권 수집 + 1차 추출
    python -m model.party --verify     # 판정자 2인 정밀도 검정
"""
import argparse
import json
import random
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import requests

from pipeline.config import CACHE_DIR, DB_PATH, load_env

SEED = 0
PILOT_TRDAR = 30
# 검색 API 상한과 같게 둔다. 60 으로 돌린 1 차 전량 수집은 커버리지 31.5% 로
# §J-1-③ 기준(40%)에 미달했다 — 문턱을 내리는 대신 데이터를 늘린다. 검색 호출
# 수는 그대로고(이미 display=100 을 받아 40 건을 버리고 있었다) LLM 추출만 는다.
PER_TRDAR = 100
SEARCH_DISPLAY = 100
EXTRACT_MODEL = "gpt-5.4-mini"
# A different model for the evidence pass. Same model judging its own output is
# not an independent check — §I-19 uses distinct judges for this reason.
EVIDENCE_MODEL = "gpt-4o-mini"
API = "https://openapi.naver.com/v1/search/blog.json"
TAG = re.compile(r"<[^>]+>")
OUT = CACHE_DIR / "party"

CLASSES = ("alone", "couple", "family", "friend", "work")

# §J-1-③, fixed before the run.
PRECISION_MIN = 0.60
WILSON_MIN = 0.45
KAPPA_MIN = 0.40
MIN_POSTS_PER_TRDAR = 5
COVERAGE_MIN = 0.40

EXTRACT_PROMPT = """다음은 한국어 음식점 블로그 글의 일부다.
**글쓴이가 누구와 함께 갔는지**만 판정하라. 맛·가격·분위기는 무시한다.

가능한 값은 하나만 고른다:
  alone   혼자
  couple  연인·배우자와 둘이
  family  가족(부모·자녀·형제)과
  friend  친구·지인과
  work    직장 동료·회식·모임

**규칙**
- 근거가 되는 원문을 20자 이내로 그대로 인용하라. 인용할 문구가 없으면
  label 과 quote 를 모두 null 로 두어라.
- 추측하지 마라. "분위기가 좋다"는 연인이라는 근거가 아니다.
- 인용은 반드시 글에 실제로 있는 문자열이어야 한다.

JSON 으로만 답하라:
{"items": [{"i": <글 번호>, "label": "alone"|"couple"|"family"|"friend"|"work"|null,
            "quote": "<원문 20자 이내>"|null}]}
글 번호는 주어진 것을 그대로 쓴다.

"""


def _naver_headers():
    env = load_env()
    for k in ("NAVER_CLIENT_ID", "NAVER_CLIENT_SECRET"):
        if not env.get(k):
            raise RuntimeError(f"{k} 없음 — .env 를 확인할 것")
    return {"X-Naver-Client-Id": env["NAVER_CLIENT_ID"],
            "X-Naver-Client-Secret": env["NAVER_CLIENT_SECRET"]}


def targets(n=PILOT_TRDAR):
    """Stratified by 상권 유형 so the pilot is not all 발달상권.

    A pilot drawn only from busy districts would answer a different question
    than the product asks — most cells a user clicks are 골목상권.
    """
    import sqlite3
    con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    rows = con.execute(
        "SELECT trdar_cd, trdar_nm, trdar_se_nm FROM trdar_area "
        "WHERE trdar_nm IS NOT NULL ORDER BY trdar_cd").fetchall()
    con.close()
    by_type = {}
    for cd, nm, se in rows:
        by_type.setdefault(se or "기타", []).append((cd, nm, se))
    rng = random.Random(SEED)
    for pool in by_type.values():
        rng.shuffle(pool)
    # Equal per type, then top up from the largest remaining pools. Equal shares
    # measure precision on every type; proportional would put 66% of the pilot in
    # 골목상권 and leave 관광특구 (6 districts total) unmeasured.
    order = sorted(by_type)
    per = max(1, n // len(order))
    out, taken = [], {}
    for se in order:
        take = by_type[se][:per]
        taken[se] = len(take)
        out.extend(take)
    i = 0
    while len(out) < n and i < 1000:
        se = order[i % len(order)]
        pool = by_type[se]
        if taken[se] < len(pool):
            out.append(pool[taken[se]])
            taken[se] += 1
        i += 1
    rng.shuffle(out)
    return out[:n]


class CollectFailed(RuntimeError):
    """The search API could not be reached for this district.

    Distinct from «this district has no posts». Collapsing the two writes a
    «검색 결과 없음» marker row, which makes `_done_districts()` count the
    district as finished and a resumed run skip it forever — the resumability
    fails exactly when it is needed.
    """


def fetch_posts(headers, name, want=PER_TRDAR, tries=5):
    """Blog snippets for one commercial district. The API returns a
    search-relevance-selected 147-char description, which is exactly the corpus
    §19-A found too thin — that limitation is inherited, not solved.

    Raises CollectFailed when every retry failed; returns [] only when the API
    answered and had nothing.
    """
    last = "이유 미상"
    for attempt in range(tries):
        try:
            # "서울" is not decoration. The pilot pulled 광주 송정역 posts for
            # Seoul's 송정역 — a district name alone is not unique nationally,
            # and posts about another city would describe this one.
            r = requests.get(API, headers=headers, timeout=20, params={
                "query": f"서울 {name} 맛집", "display": SEARCH_DISPLAY,
                "sort": "sim"})
            if r.status_code != 200:
                # Exponential, not linear. Measured: 59 districts exhausted three
                # 1~2s retries and were written off, yet the same queries each
                # returned 100 items when retried later. A retry policy too
                # shallow for the API turns a blip into a permanent data gap.
                last = f"HTTP {r.status_code}"
                time.sleep(min(30, 2 ** attempt))
                continue
            out = []
            for it in r.json().get("items", []):
                txt = TAG.sub("", f"{it.get('title','')} {it.get('description','')}")
                txt = txt.replace("&quot;", '"').replace("&amp;", "&").strip()
                if len(txt) >= 40:
                    out.append({"date": (it.get("postdate") or "").strip(),
                                "text": txt, "link": it.get("link")})
                if len(out) >= want:
                    break
            return out
        except requests.RequestException as exc:
            last = type(exc).__name__
            time.sleep(min(30, 2 ** attempt))
    raise CollectFailed(f"검색 API 실패({tries}회): {name} — 마지막 사유 {last}")


def _client():
    key = load_env().get("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("OPENAI_API_KEY 없음")
    from openai import OpenAI
    return OpenAI(api_key=key, max_retries=0)   # retry is handled below


def _complete(client, model, prompt, tries=6):
    """One chat call with backoff on the org's token-per-minute limit.

    Measured: five concurrent districts against a 200k TPM ceiling failed 177 of
    408 attempts. Those districts were simply dropped — recoverable only because
    `full()` skips what is already on disk, but 43% of the run was being spent
    producing nothing. Backing off here is what makes the concurrency usable.
    """
    for attempt in range(tries):
        try:
            return client.chat.completions.create(
                model=model, response_format={"type": "json_object"},
                messages=[{"role": "user", "content": prompt}])
        except Exception as exc:
            if "rate_limit" not in str(exc) and "429" not in str(exc):
                raise
            if attempt == tries - 1:
                raise
            time.sleep(min(30, 2 ** attempt) * (1 + 0.3 * (attempt % 3)))
    return None


def extract(client, posts, model=EXTRACT_MODEL, batch=10):
    """Label a district's posts. Returns one dict per post, aligned by index."""
    labels = [None] * len(posts)
    for start in range(0, len(posts), batch):
        chunk = posts[start:start + batch]
        body = "\n\n".join(f"[{start + i}] {p['text']}" for i, p in enumerate(chunk))
        r = _complete(client, model, EXTRACT_PROMPT + body)
        try:
            got = json.loads(r.choices[0].message.content).get("items", [])
        except json.JSONDecodeError:
            continue
        for item in got:
            try:
                i = int(item.get("i"))
            except (TypeError, ValueError):
                continue
            if 0 <= i < len(posts):
                labels[i] = _clean(item, posts[i]["text"])
    return labels


EVIDENCE_PROMPT = """각 항목은 블로그 글에서 뽑은 «인용문»과, 그 인용문이 근거라고
주장된 «동반자 라벨»이다.

**인용문만 보고** 그 라벨이 정당한지 판정하라. 원문 전체는 주지 않는다 —
인용문 자체가 근거로 충분한지가 질문이다.

  alone 혼자 · couple 연인·배우자 · family 가족 · friend 친구·지인 ·
  work 직장·회식

인용문에 동반자 정보가 없으면 supports 는 false 다.
예: «들른 정릉아리랑시장의» → 동반자 정보 없음 → false
    «와이프랑 오랜만에» → couple 근거 → true

JSON 으로만 답하라: {"items": [{"i": <번호>, "supports": true|false}]}

"""


def evidence_pass(client, labelled, model=EVIDENCE_MODEL, batch=20):
    """Second, independent judgement: does the quote actually support the label?

    The lexical rule in `_clean` only proves the quote was copied, not that it
    is evidence. The pilot labelled a post `alone` on the strength of
    «들른 정릉아리랑시장의», which says nothing about who came along — it passed
    every rule and was still wrong. Whether a phrase supports a claim is a
    semantic question, so it is asked as one, by a different model, with the
    surrounding text withheld so the quote has to carry the weight.
    """
    verdicts = [None] * len(labelled)
    for start in range(0, len(labelled), batch):
        chunk = labelled[start:start + batch]
        body = "\n".join(
            f'[{start + i}] 라벨={r["label"]} 인용=«{r["quote"]}»'
            for i, r in enumerate(chunk))
        r = _complete(client, model, EVIDENCE_PROMPT + body)
        try:
            got = json.loads(r.choices[0].message.content).get("items", [])
        except json.JSONDecodeError:
            continue
        for item in got:
            try:
                i = int(item.get("i"))
            except (TypeError, ValueError):
                continue
            if 0 <= i < len(labelled):
                verdicts[i] = bool(item.get("supports"))
    return verdicts


def _clean(item, text):
    """Void a label whose quote is missing or not actually in the post.

    This is anti-fabrication only — it proves the phrase was copied, not that it
    means anything. `evidence_pass` is what decides whether it is evidence."""
    label, quote = item.get("label"), (item.get("quote") or "").strip()
    if label not in CLASSES:
        return {"label": None, "quote": None, "void": "라벨 없음"}
    if not quote:
        return {"label": None, "quote": None, "void": "인용 없음"}
    if len(quote) > 20:
        return {"label": None, "quote": quote, "void": "인용 20자 초과"}
    if quote not in text:
        return {"label": None, "quote": quote, "void": "인용이 원문에 없음"}
    return {"label": label, "quote": quote, "void": None}


def pilot(n=PILOT_TRDAR, verbose=True):
    headers = _naver_headers()
    client = _client()
    OUT.mkdir(parents=True, exist_ok=True)
    picks = targets(n)
    if verbose:
        print(f"파일럿 상권 {len(picks)}개 (유형 층화 · 시드 {SEED})")

    with ThreadPoolExecutor(max_workers=4) as pool:
        fetched = list(pool.map(lambda t: fetch_posts(headers, t[1]), picks))

    records, empty = [], 0
    for (cd, nm, se), posts in zip(picks, fetched):
        if not posts:
            empty += 1
            continue
        labels = extract(client, posts)
        for p, lab in zip(posts, labels):
            lab = lab or {"label": None, "quote": None, "void": "판정 실패"}
            records.append({"trdar_cd": cd, "trdar_nm": nm, "trdar_se": se,
                            "date": p["date"], "text": p["text"], **lab})
        if verbose:
            got = sum(1 for l in labels if l and l["label"])
            print(f"  {nm[:16]:<18}{se or '':<8} 글 {len(posts):>3} · 라벨 {got:>3}")

    labelled = [r for r in records if r["label"]]
    if labelled:
        verdicts = evidence_pass(client, labelled)
        dropped = 0
        for r, ok in zip(labelled, verdicts):
            r["evidence_ok"] = ok
            if ok is not True:
                r["void"] = "인용이 라벨의 근거가 아님"
                r["label"] = None
                dropped += 1
        if verbose:
            print(f"\n인용 근거 검증({EVIDENCE_MODEL}): "
                  f"{len(labelled) - dropped}/{len(labelled)} 통과 · {dropped} 탈락")

    path = OUT / "pilot.json"
    path.write_text(json.dumps(records, ensure_ascii=False, indent=2),
                    encoding="utf-8")
    if verbose:
        _pilot_report(records, len(picks), empty)
        print(f"  -> {path}")
    return records


def _pilot_report(records, n_trdar, empty):
    n = len(records)
    labelled = [r for r in records if r["label"]]
    voids = {}
    for r in records:
        if r["void"]:
            voids[r["void"]] = voids.get(r["void"], 0) + 1
    print(f"\n수집 {n:,}글 (상권 {n_trdar}개 중 {empty}개 결과 없음)")
    print(f"라벨 부착 {len(labelled):,} · 기권 {n - len(labelled):,} "
          f"({(n - len(labelled)) / n * 100:.1f}%)" if n else "수집 0")
    for k, v in sorted(voids.items(), key=lambda x: -x[1]):
        print(f"    기권 사유 · {k}: {v:,}")
    dist = {}
    for r in labelled:
        dist[r["label"]] = dist.get(r["label"], 0) + 1
    print("  클래스 분포: " + "  ".join(
        f"{c} {dist.get(c, 0)}" for c in CLASSES))

    per = {}
    for r in labelled:
        per[r["trdar_cd"]] = per.get(r["trdar_cd"], 0) + 1
    ok = sum(1 for v in per.values() if v >= MIN_POSTS_PER_TRDAR)
    print(f"  라벨 {MIN_POSTS_PER_TRDAR}건 이상 상권: {ok}/{n_trdar} "
          f"({ok / n_trdar * 100:.0f}%) — §J-1 커버리지 기준 {COVERAGE_MIN*100:.0f}%")


# -------------------------------------------------------------------- full

# §J-1 파일럿에서 표기 문턱을 통과한 클래스만. 나머지는 수집·저장은 하되
# 서빙에 내보내지 않는다 — 재검정 때 다시 수집하지 않기 위해서다.
APPROVED_CLASSES = ("family", "work")
FULL_PATH = OUT / "full.jsonl"
_write_lock = __import__("threading").Lock()


def _done_districts():
    if not FULL_PATH.is_file():
        return set()
    done = set()
    for line in FULL_PATH.open(encoding="utf-8"):
        try:
            done.add(json.loads(line)["trdar_cd"])
        except (json.JSONDecodeError, KeyError):
            continue
    return done


def _one_district(headers, client, cd, nm, se):
    posts = fetch_posts(headers, nm)
    records = []
    if posts:
        labels = extract(client, posts)
        for p, lab in zip(posts, labels):
            lab = lab or {"label": None, "quote": None, "void": "판정 실패"}
            records.append({"trdar_cd": cd, "trdar_nm": nm, "trdar_se": se,
                            "date": p["date"], "text": p["text"], **lab})
        labelled = [r for r in records if r["label"]]
        if labelled:
            for r, ok in zip(labelled, evidence_pass(client, labelled)):
                r["evidence_ok"] = ok
                if ok is not True:
                    r["void"] = "인용이 라벨의 근거가 아님"
                    r["label"] = None
    # A district the API answered for but that genuinely has no posts still gets
    # a marker row, or a resumed run would retry it forever. A district whose
    # fetch *failed* never reaches here — CollectFailed propagates so the
    # district stays unwritten and the next run picks it up.
    if not records:
        records = [{"trdar_cd": cd, "trdar_nm": nm, "trdar_se": se,
                    "date": None, "text": None, "label": None, "quote": None,
                    "void": "검색 결과 없음"}]
    with _write_lock:
        with FULL_PATH.open("a", encoding="utf-8") as f:
            for r in records:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return cd, sum(1 for r in records if r["label"])


def full(workers=3, verbose=True):
    """All 1,649 districts. Appends per district and skips what is already on
    disk, so an interrupted run resumes instead of starting over."""
    import sqlite3
    headers = _naver_headers()
    client = _client()
    OUT.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    rows = con.execute(
        "SELECT trdar_cd, trdar_nm, trdar_se_nm FROM trdar_area "
        "WHERE trdar_nm IS NOT NULL ORDER BY trdar_cd").fetchall()
    con.close()
    done = _done_districts()
    todo = [r for r in rows if r[0] not in done]
    if verbose:
        print(f"상권 {len(rows):,} · 완료 {len(done):,} · 남은 {len(todo):,}",
              flush=True)
    if not todo:
        return 0
    t0 = time.time()
    n_lab = n_fail = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = [pool.submit(_one_district, headers, client, cd, nm, se)
                for cd, nm, se in todo]
        for i, fut in enumerate(futs, 1):
            try:
                _, got = fut.result()
                n_lab += got
            except Exception as exc:
                n_fail += 1
                print(f"  [실패] {type(exc).__name__}: {exc}", flush=True)
            if verbose and i % 50 == 0:
                el = time.time() - t0
                eta = el / i * (len(todo) - i) / 60
                print(f"  {i:,}/{len(todo):,} · 라벨 {n_lab:,} · 실패 {n_fail:,} · "
                      f"경과 {el/60:.0f}분 · 남은 약 {eta:.0f}분", flush=True)
    print(f"완료 · 라벨 {n_lab:,} · 실패 {n_fail:,} · "
          f"{(time.time()-t0)/60:.0f}분", flush=True)
    # 실패가 남았으면 0 을 반환하지 않는다. bootstrap 의 party 단계는 --full 뒤에
    # --load 를 잇는데, 여기서 0 을 주면 일부만 걷힌 상태가 서빙 테이블로 승격된다.
    # 실패한 상권은 파일에 없으므로 같은 명령을 다시 치면 그것만 다시 받는다.
    if n_fail:
        print(f"  {n_fail:,}개 상권이 실패했다 — 같은 명령을 다시 치면 그것만 받는다",
              flush=True)
        return 1
    return 0


# -------------------------------------------------------------------- load

# 실측 정밀도(§J-1)는 `service/api.py` 의 PARTY_PRECISION 한 곳에만 둔다. 여기에도
# 같은 숫자를 두면 재검정 때 한쪽만 고쳐지고, 어느 쪽이 화면에 나가는지 알 수 없다.

PARTY_SCHEMA = """
CREATE TABLE IF NOT EXISTS trdar_party (
  trdar_cd      TEXT,
  party         TEXT,
  n             INTEGER,
  posts_scanned INTEGER,
  PRIMARY KEY (trdar_cd, party)
);
"""


def load(verbose=True):
    """full.jsonl -> kb.db. Only the classes §J-1 admitted are written.

    Districts below MIN_POSTS_PER_TRDAR get no row at all rather than zeros —
    «too few posts to say» and «nobody comes with family» are different claims
    and the schema must not merge them (CLAUDE.md 규칙 1).
    """
    import sqlite3
    if not FULL_PATH.is_file():
        raise RuntimeError("full.jsonl 없음 — 먼저 --full")
    # 파일 전체를 먼저 읽어 검증한다. 깨진 행을 건너뛰고 진행하면 그 아래에서
    # DELETE 가 돌아, 잘린 파일이 조용히 서빙 테이블 축소로 이어진다. 수집이
    # 중간에 죽으면 마지막 줄이 잘릴 수 있고 그게 흔한 경우다.
    parsed = []
    for lineno, line in enumerate(FULL_PATH.open(encoding="utf-8"), 1):
        if not line.strip():
            continue
        try:
            parsed.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                f"{FULL_PATH.name} {lineno}행이 깨졌다: {exc}. "
                f"DB 는 건드리지 않았다 — 그 줄을 지우고 다시 실행할 것"
            ) from exc

    scanned, counts = {}, {}
    for r in parsed:
        cd = r["trdar_cd"]
        if r.get("text"):
            scanned[cd] = scanned.get(cd, 0) + 1
        lab = r.get("label")
        if lab in APPROVED_CLASSES:
            counts.setdefault(cd, {}).setdefault(lab, 0)
            counts[cd][lab] += 1

    rows = []
    for cd, per in counts.items():
        if sum(per.values()) < MIN_POSTS_PER_TRDAR:
            continue
        for party in APPROVED_CLASSES:
            rows.append((cd, party, per.get(party, 0), scanned.get(cd, 0)))

    con = sqlite3.connect(DB_PATH)
    con.executescript(PARTY_SCHEMA)
    con.execute("DELETE FROM trdar_party")
    con.executemany(
        "INSERT INTO trdar_party (trdar_cd, party, n, posts_scanned) "
        "VALUES (?,?,?,?)", rows)
    con.commit()
    con.close()
    if verbose:
        served = len({r[0] for r in rows})
        print(f"trdar_party: {len(rows):,}행 · 상권 {served:,}개 "
              f"(수집 {len(scanned):,} 중 {MIN_POSTS_PER_TRDAR}건 이상)")
        print(f"  커버리지 {served/max(1,len(scanned))*100:.0f}% "
              f"(§J-1 기준 {COVERAGE_MIN*100:.0f}%)")
    return len(rows)


# ------------------------------------------------------------------ verify

JUDGE_PROMPT = """각 항목은 한국어 음식점 블로그 글의 일부다.
**글쓴이가 누구와 함께 갔는지** 판정하라.

  alone 혼자 · couple 연인·배우자와 둘이 · family 가족(부모·자녀·형제)과 ·
  friend 친구·지인과 · work 직장 동료·회식·모임

글에 동반자에 대한 명시적 단서가 없으면 null 이다. 추측하지 마라.

JSON 으로만 답하라: {"items": [{"i": <번호>, "label": <값 또는 null>}]}

"""

JUDGES = (("A", EXTRACT_MODEL, False), ("B", EVIDENCE_MODEL, True))


def _wilson(k, n, z=1.96):
    if not n:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / d
    return (max(0.0, c - h), min(1.0, c + h))


def _judge(client, rows, model, reverse, batch=15):
    """One judge, blind to the first-pass label. Reversed order for the second
    judge so position in the batch cannot drive agreement."""
    idx = list(range(len(rows)))
    if reverse:
        idx = idx[::-1]
    out = [None] * len(rows)
    for start in range(0, len(idx), batch):
        chunk = idx[start:start + batch]
        body = "\n\n".join(f"[{i}] {rows[i]['text']}" for i in chunk)
        r = _complete(client, model, JUDGE_PROMPT + body)
        try:
            got = json.loads(r.choices[0].message.content).get("items", [])
        except json.JSONDecodeError:
            continue
        for item in got:
            try:
                i = int(item.get("i"))
            except (TypeError, ValueError):
                continue
            if 0 <= i < len(rows):
                lab = item.get("label")
                out[i] = lab if lab in CLASSES else None
    return out


def verify(per_class=30, verbose=True):
    """§J-1-③ — positive precision per class, two blind judges."""
    path = OUT / "pilot.json"
    if not path.is_file():
        raise RuntimeError("pilot.json 없음 — 먼저 --pilot")
    records = [r for r in json.loads(path.read_text(encoding="utf-8"))
               if r.get("label")]
    rng = random.Random(SEED)
    sample = []
    for c in CLASSES:
        pool = [r for r in records if r["label"] == c]
        rng.shuffle(pool)
        sample.extend(pool[:per_class])
    if verbose:
        print(f"검정 표본 {len(sample)}건 (클래스당 최대 {per_class})")

    client = _client()
    votes = {}
    for name, model, rev in JUDGES:
        votes[name] = _judge(client, sample, model, rev)
        if verbose:
            print(f"  판정자 {name} ({model}{', 역순' if rev else ''}) 완료")

    rows, kappa_pairs = [], []
    for c in CLASSES:
        ix = [i for i, r in enumerate(sample) if r["label"] == c]
        if not ix:
            continue
        hits = {n: sum(1 for i in ix if votes[n][i] == c) for n, _, _ in JUDGES}
        n = len(ix)
        both = sum(1 for i in ix
                   if votes["A"][i] == c and votes["B"][i] == c)
        lo, hi = _wilson(both, n)
        rows.append({"class": c, "n": n, **{f"judge_{k}": v for k, v in hits.items()},
                     "both": both, "precision": both / n,
                     "wilson_lo": lo, "wilson_hi": hi})
    for i in range(len(sample)):
        kappa_pairs.append((votes["A"][i], votes["B"][i]))
    kappa = _kappa(kappa_pairs)

    if verbose:
        _verify_report(rows, kappa)
    (OUT / "verify.json").write_text(
        json.dumps({"rows": rows, "kappa": kappa}, ensure_ascii=False, indent=2),
        encoding="utf-8")
    return rows, kappa


def _kappa(pairs):
    """Cohen's kappa between the two judges over all labels including null."""
    cats = sorted({x for p in pairs for x in p}, key=lambda v: (v is None, v))
    n = len(pairs)
    if not n:
        return None
    agree = sum(1 for a, b in pairs if a == b) / n
    pa = {c: sum(1 for a, _ in pairs if a == c) / n for c in cats}
    pb = {c: sum(1 for _, b in pairs if b == c) / n for c in cats}
    exp = sum(pa[c] * pb[c] for c in cats)
    return (agree - exp) / (1 - exp) if exp < 1 else None


def _verify_report(rows, kappa):
    print(f"\n{'클래스':<10}{'n':>5}{'판정A':>7}{'판정B':>7}{'양쪽':>7}"
          f"{'정밀도':>9}{'Wilson 하한':>13}  판정")
    for r in rows:
        ok = (r["precision"] >= PRECISION_MIN and r["wilson_lo"] >= WILSON_MIN)
        print(f"{r['class']:<10}{r['n']:>5}{r['judge_A']:>7}{r['judge_B']:>7}"
              f"{r['both']:>7}{r['precision']:>9.3f}{r['wilson_lo']:>13.3f}"
              f"  {'PASS' if ok else 'FAIL'}")
    print(f"\n  기준: 정밀도 ≥ {PRECISION_MIN} 이고 Wilson 하한 ≥ {WILSON_MIN}")
    kv = f"{kappa:.3f}" if kappa is not None else "—"
    print(f"  판정자 2인 κ = {kv}  (기준 ≥ {KAPPA_MIN})")
    print("  ※ 정밀도는 «양쪽 판정자가 모두 같은 라벨» 기준이다 — 한쪽만 맞은 것은 세지 않는다")


def main():
    ap = argparse.ArgumentParser(description="방문객 동반자 표기 (§J-1)")
    ap.add_argument("--pilot", action="store_true", help="30상권 수집 + 1차 추출")
    ap.add_argument("--verify", action="store_true", help="판정자 2인 정밀도 검정")
    ap.add_argument("--full", action="store_true", help="전량 1,649상권 (이어받기)")
    ap.add_argument("--load", action="store_true", help="full.jsonl -> kb.db")
    ap.add_argument("--n", type=int, default=PILOT_TRDAR)
    a = ap.parse_args()
    if a.pilot:
        pilot(a.n)
    if a.verify:
        verify()
    if a.full:
        full()
    if a.load:
        load()
    if not (a.pilot or a.verify or a.full or a.load):
        ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
