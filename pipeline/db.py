"""SQLite schema.

Design rule that the whole project rests on: a feature that has no source
data is NULL, never 0. A grid cell outside any commercial area genuinely has
no sales figure - writing 0 there would make it rank as "worst location"
instead of "unknown", which is a silent lie in the recommendation.
"""
import sqlite3

from .config import DB_PATH

SCHEMA = """
PRAGMA journal_mode=WAL;

-- grid cells actually touched by data (not the full 163k bbox)
CREATE TABLE IF NOT EXISTS grid (
  grid_id       TEXT PRIMARY KEY,
  center_lon    REAL NOT NULL,
  center_lat    REAL NOT NULL,
  adstrd_cd     TEXT,
  trdar_cd      TEXT,
  trdar_se_nm   TEXT,
  has_sales_data INTEGER NOT NULL DEFAULT 0
);

-- 인허가 정규화 (원본 JSON은 pipeline/cache/licence.jsonl 이 보관)
CREATE TABLE IF NOT EXISTS licence (
  mgtno         TEXT PRIMARY KEY,
  bplcnm        TEXT,
  uptae         TEXT,
  addr          TEXT,
  open_y        INTEGER,
  open_m        INTEGER,
  close_y       INTEGER,
  close_m       INTEGER,
  state         TEXT,          -- 영업/정상 | 폐업 | ...
  is_closed     INTEGER,
  site_area     REAL,
  lon           REAL,
  lat           REAL,
  grid_id       TEXT,
  succession_suspect INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_licence_grid ON licence(grid_id);
CREATE INDEX IF NOT EXISTS ix_licence_open ON licence(open_y);
CREATE INDEX IF NOT EXISTS ix_licence_uptae ON licence(uptae);

-- 소상공인 상가정보 (현재 영업 스냅샷, 필지/층 해상도)
CREATE TABLE IF NOT EXISTS store (
  bizes_id      TEXT PRIMARY KEY,
  bizes_nm      TEXT,
  inds_lcls_nm  TEXT,
  inds_mcls_nm  TEXT,
  inds_scls_nm  TEXT,
  adong_cd      TEXT,
  pnu           TEXT,
  bldg_nm       TEXT,
  flr_no        TEXT,
  lon           REAL,
  lat           REAL,
  grid_id       TEXT
);
CREATE INDEX IF NOT EXISTS ix_store_grid ON store(grid_id);

-- 상권 영역
CREATE TABLE IF NOT EXISTS trdar_area (
  trdar_cd      TEXT PRIMARY KEY,
  trdar_nm      TEXT,
  trdar_se_cd   TEXT,
  trdar_se_nm   TEXT,
  signgu_cd     TEXT,
  adstrd_cd     TEXT,
  area_m2       REAL,
  equiv_radius_m REAL,
  center_lon    REAL,
  center_lat    REAL
);

-- 상권 × 분기 × 요식업종 추정매출
CREATE TABLE IF NOT EXISTS trdar_sales (
  quarter       TEXT,
  trdar_cd      TEXT,
  induty_cd     TEXT,
  sales_amt     REAL,
  sales_cnt     REAL,
  mdwk_amt      REAL,
  wkend_amt     REAL,
  tz_00_06      REAL, tz_06_11 REAL, tz_11_14 REAL,
  tz_14_17      REAL, tz_17_21 REAL, tz_21_24 REAL,
  PRIMARY KEY (quarter, trdar_cd, induty_cd)
);

-- 상권 × 분기 × 요식업종 점포/개폐업
CREATE TABLE IF NOT EXISTS trdar_store (
  quarter       TEXT,
  trdar_cd      TEXT,
  induty_cd     TEXT,
  stor_co       REAL,
  similar_stor_co REAL,
  frc_stor_co   REAL,
  opbiz_rt      REAL,
  clsbiz_rt     REAL,
  PRIMARY KEY (quarter, trdar_cd, induty_cd)
);

-- 상권 × 분기 유동인구
CREATE TABLE IF NOT EXISTS trdar_flpop (
  quarter       TEXT,
  trdar_cd      TEXT,
  tot_flpop     REAL,
  tz_00_06      REAL, tz_06_11 REAL, tz_11_14 REAL,
  tz_14_17      REAL, tz_17_21 REAL, tz_21_24 REAL,
  PRIMARY KEY (quarter, trdar_cd)
);

-- 생활인구: 행정동 × 시간대 평균 프로파일
CREATE TABLE IF NOT EXISTS lvpop_profile (
  adstrd_cd     TEXT,
  tmzon         TEXT,
  avg_lvpop     REAL,
  n_days        INTEGER,
  PRIMARY KEY (adstrd_cd, tmzon)
);

-- 코호트 생존율 (전량 기준)
CREATE TABLE IF NOT EXISTS cohort_survival (
  scope         TEXT,          -- 'seoul' | 'uptae:한식' | 'grid:...'
  scope_key     TEXT,
  open_year     INTEGER,
  opened        INTEGER,
  survive_1y    REAL, observable_1y INTEGER,
  survive_2y    REAL, observable_2y INTEGER,
  survive_3y    REAL, observable_3y INTEGER,
  survive_5y    REAL, observable_5y INTEGER,
  succession_excluded INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (scope, scope_key, open_year, succession_excluded)
);

-- 최종 피처: 격자당 정확히 1행
CREATE TABLE IF NOT EXISTS grid_feature (
  grid_id       TEXT PRIMARY KEY,
  center_lon    REAL NOT NULL,
  center_lat    REAL NOT NULL,
  adstrd_cd     TEXT,
  trdar_cd      TEXT,
  has_sales_data INTEGER NOT NULL,
  -- 경쟁
  food_store_cnt      INTEGER,
  food_store_cnt_r1   INTEGER,   -- 이웃 8칸 포함
  competitor_same_uptae TEXT,    -- json: uptae -> count
  franchise_cnt       INTEGER,
  -- 생존
  hist_open_cnt       INTEGER,
  hist_close_cnt      INTEGER,
  survive_3y_local    REAL,      -- NULL when sample too small
  survive_3y_n        INTEGER,
  -- 수요 (행정동 단위 — 격자로 배분하지 않는다. docs 공간해상도 원칙 참조)
  lvpop_day           REAL,
  lvpop_night         REAL,
  -- 센서스 수요 (SGIS 행정동, 폴리곤 매칭)
  sgis_adm_cd         TEXT,
  ppltn_dnsty         REAL,
  avg_age             REAL,
  avg_fmember_cnt     REAL,
  corp_cnt            REAL,   -- 사업체 수 = 주간 직장수요 대리변수
  tot_worker          REAL,   -- 종사자 수
  worker_per_resident REAL,   -- 종사자/거주인구 = 직장상권 성격
  -- 매출 (상권 밖이면 NULL, 절대 0 아님)
  sales_amt           REAL,
  sales_cnt           REAL,
  flpop               REAL,
  -- 메타
  confidence          TEXT NOT NULL   -- 'full' | 'partial'
);

-- API 호출 기록 (일일 한도 관리)
CREATE TABLE IF NOT EXISTS api_log (
  day           TEXT,
  service       TEXT,
  calls         INTEGER,
  PRIMARY KEY (day, service)
);
"""


def connect():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def connect_ro():
    uri = f"{DB_PATH.resolve().as_uri()}?mode=ro"
    con = sqlite3.connect(uri, uri=True)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA query_only=ON")
    return con


def init():
    con = connect()
    con.executescript(SCHEMA)
    con.commit()
    return con


if __name__ == "__main__":
    con = init()
    tables = [r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
    print(f"db: {DB_PATH}")
    print(f"tables ({len(tables)}): {', '.join(tables)}")
