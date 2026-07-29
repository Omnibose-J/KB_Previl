"""Pipeline-wide constants. Single source of truth for units and limits.

Three coordinate systems are in play and mixing them silently produces
plausible-but-wrong locations, so every CRS is named here and nowhere else:
  EPSG:5174 - LOCALDATA licensing X/Y (Korean 1985 Modified Central Belt)
  EPSG:5181 - Seoul commercial-area centroids (GRS80 TM, 중부원점)
  EPSG:4326 - WGS84 lon/lat, the interchange format
  EPSG:5179 - UTM-K, the metric grid we bucket into

Both were settled empirically (probe/p8_crs.py), not from documentation. The
candidates share an origin and differ only by datum shift, so a wrong pick
still lands inside Seoul and passes every internal check while displacing every
point 100-200m - one to two grid cells. Reverse-geocoding a sample against each
row's own address is the only thing that separates them:
  licensing : 5174 = 120/120 (100.0%) | 2097 = 90.8% | 5181 = 89.2%
  commercial: 5181 =  80/80  (100.0%) | 2097 = 93.8% | 5174 = 90.0%
Re-run that probe before trusting a CRS change.
"""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Data lives outside version control (229MB db, 807MB cache) and is shared by
# every lane. A git worktree gets its own checkout but must NOT get its own
# copy of these, so both paths are overridable:
#   KB_DB    - absolute path to kb.db
#   KB_CACHE - absolute path to the raw collection cache
#   KB_ENV   - absolute path to the .env holding API keys
# Unset means "the copy next to this checkout", which is right for the primary
# tree and wrong for a worktree - lanes/setup-worktrees.ps1 sets them.
DB_PATH = Path(os.environ.get("KB_DB") or (ROOT / "kb.db"))
CACHE_DIR = Path(os.environ.get("KB_CACHE") or (ROOT / "pipeline" / "cache"))
ENV_PATH = Path(os.environ.get("KB_ENV") or (ROOT / ".env"))
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# --- coordinate systems -------------------------------------------------
CRS_LICENCE = "EPSG:5174"
CRS_TRDAR = "EPSG:5181"
CRS_WGS84 = "EPSG:4326"
CRS_GRID = "EPSG:5179"

GRID_SIZE_M = 100

# Seoul bounding box in WGS84, used only as a sanity gate on transforms.
SEOUL_BBOX = (126.73, 37.41, 127.27, 37.72)   # lon_min, lat_min, lon_max, lat_max

# --- Seoul Open Data API ------------------------------------------------
SEOUL_BASE = "http://openapi.seoul.go.kr:8088"
SEOUL_PAGE = 1000
# Daily quota for a standard key. Not published per-response, so we budget
# conservatively and stop rather than getting cut off mid-load.
SEOUL_DAILY_BUDGET = 900

SVC_LICENCE = "LOCALDATA_072404"        # 일반음식점 인허가
SVC_LICENCE_REST = "LOCALDATA_072405"   # 휴게음식점

# 휴게음식점 중 «음식점»으로 셀 것. 카페·베이커리·패스트푸드는 여기 있고,
# 편의점 5,917 · 백화점 527 · 철도역구내 105 는 인허가만 휴게음식점이지 경쟁
# 음식점이 아니라 뺀다. «기타 휴게음식점» 7,353 도 뺀다 — 상호를 보면 GS25·
# 씨유 같은 편의점과 카페·도넛이 섞여 있어 어느 쪽으로도 셀 수 없다.
#
# 레인 B(service.api)와 레인 A(model.concept_mix)가 같은 집합을 써야 화면의
# «음식점 수»와 «주변에 많은 가게»가 같은 모집단을 말한다. 두 곳에 복사하면
# 한쪽만 고쳐져 조용히 갈라지므로 여기 한 곳에서 정한다.
REST_EATERY_UPTAE = (
    "커피숍", "일반조리판매", "다방", "패스트푸드", "과자점",
    "푸드트럭", "아이스크림", "전통찻집", "떡카페", "키즈카페",
)

# 우리 업태 -> 서울 상권분석 «서비스업종» 코드. 매출·권리금·부담률이 전부
# 이 매핑을 타므로 한 곳에서만 정한다.
#
# service/ 안에 두면 순환이 생긴다 — goodwill 과 estimation 이 api 를 import
# 하는데 api 도 이 매핑이 필요하다. 이 모듈은 아무것도 import 하지 않으므로
# 세 곳이 모두 안전하게 가져갈 수 있다.
#
# 없는 업태(기타·외국음식전문점)는 «빠뜨린 것» 이 아니라 원천 분류에 대응이
# 없는 것이다. 억지로 붙이면 다른 업종의 매출을 그 업종 값이라고 말하게 된다.
UPTAE_INDUTY = {
    "한식": "CS100001",
    "식육(숯불구이)": "CS100001",
    "중국식": "CS100002",
    "일식": "CS100003",
    "경양식": "CS100004",
    "통닭(치킨)": "CS100007",
    "분식": "CS100008",
    "호프/통닭": "CS100009",
    "정종/대포집/소주방": "CS100009",
    "까페": "CS100010",
}
SVC_TRDAR_AREA = "TbgisTrdarRelm"       # 영역-상권
SVC_TRDAR_SALES = "VwsmTrdarSelngQq"    # 추정매출-상권
SVC_TRDAR_STORE = "VwsmTrdarStorQq"     # 점포-상권
SVC_TRDAR_FLPOP = "VwsmTrdarFlpopQq"    # 길단위인구-상권
SVC_LVPOP_DONG = "SPOP_LOCAL_RESD_DONG"  # 생활인구 행정동

# Quarter filter works as positional arg1; industry filter does NOT (measured
# 2026-07-26: passing CS100001 returns the unfiltered total). Filter client-side.
DEFAULT_QUARTER = "20261"

# --- SEMAS (소상공인) ----------------------------------------------------
SEMAS_BASE = "http://apis.data.go.kr/B553077/api/open/sdsc2"
SEMAS_FOOD_LCLS = "I2"                  # 대분류: 음식

# --- domain --------------------------------------------------------------
# Seoul commercial-analysis food-service codes, confirmed exactly 10.
FOOD_INDUTY = {
    "CS100001": "한식음식점",
    "CS100002": "중식음식점",
    "CS100003": "일식음식점",
    "CS100004": "양식음식점",
    "CS100005": "제과점",
    "CS100006": "패스트푸드점",
    "CS100007": "치킨전문점",
    "CS100008": "분식전문점",
    "CS100009": "호프-간이주점",
    "CS100010": "커피-음료",
}

# Measured baselines - verify.py fails the build if reality drifts.
EXPECT_COORD_PCT = 89.1      # licensing rows carrying X/Y (full population)
EXPECT_COORD_TOL = 2.0
# Restaurants falling inside a commercial area: 66.1% under the corrected
# EPSG:5174. probe/ recorded 57.6% but that run used EPSG:2097, which displaced
# every point 100-200m and pushed boundary shops out of their own area - the
# old figure is superseded, not a discrepancy to reconcile.
EXPECT_COVERAGE_PCT = 66.1
COVERAGE_FLOOR, COVERAGE_CEIL = 55.0, 80.0
COHORT_TOL_PP = 5.0          # vs probe/results/p5_cohort.json (CRS-independent)


def load_env():
    """Parse .env into a dict. Single implementation so every lane reads keys
    the same way and a worktree can point KB_ENV elsewhere."""
    env = {}
    if not ENV_PATH.exists():
        return env
    for line in ENV_PATH.open(encoding="utf-8-sig"):
        t = line.strip()
        if t and not t.startswith("#") and "=" in t:
            k, v = t.split("=", 1)
            env[k.strip()] = v.strip()
    return env
