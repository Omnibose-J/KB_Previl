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
