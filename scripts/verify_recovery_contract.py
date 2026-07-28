"""Read-only public-contract probe for W7 succession probability sources."""

import json
import os
from pathlib import Path
import sqlite3
import sys
import warnings

warnings.filterwarnings(
    "ignore",
    message="Using `httpx` with `starlette.testclient` is deprecated",
)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient  # noqa: E402

from pipeline.config import DB_PATH  # noqa: E402
from service.app import app  # noqa: E402
from service.goodwill import UPTAE_INDUTY  # noqa: E402


def _candidate_with_sources():
    con = sqlite3.connect(f"{DB_PATH.resolve().as_uri()}?mode=ro", uri=True)
    try:
        con.execute("PRAGMA query_only=ON")
        for uptae, induty_code in UPTAE_INDUTY.items():
            row = con.execute(
                """
                SELECT gs.grid_id
                FROM grid_score gs
                JOIN grid_feature gf ON gf.grid_id = gs.grid_id
                JOIN succession_score ss
                  ON ss.grid_id = gs.grid_id AND ss.uptae = gs.uptae
                JOIN trdar_sales sales
                  ON sales.trdar_cd = gf.trdar_cd
                 AND sales.induty_cd = ?
                JOIN trdar_store stores
                  ON stores.trdar_cd = sales.trdar_cd
                 AND stores.induty_cd = sales.induty_cd
                 AND stores.quarter = sales.quarter
                WHERE gs.uptae = ?
                  AND gf.has_sales_data = 1
                  AND stores.stor_co > 0
                ORDER BY sales.quarter DESC, gs.grid_id
                LIMIT 1
                """,
                (induty_code, uptae),
            ).fetchone()
            if row is not None:
                return row[0], uptae
    finally:
        con.close()
    raise RuntimeError("실제 매출과 M2 승계 확률을 함께 가진 후보가 없습니다.")


def main():
    grid_id, uptae = _candidate_with_sources()
    payload = {
        "gridId": grid_id,
        "uptae": uptae,
        "deposit": 5000,
        "monthlyRent": 250,
        "askingGoodwill": 12000,
        "areaM2": 65,
        "floor": 1,
    }
    previous_source = os.environ.get("KB_RECOVERY_SOURCE")
    client = TestClient(app)
    probabilities = {}
    try:
        for source in ("constant", "survival_curve_proxy", "m2"):
            os.environ["KB_RECOVERY_SOURCE"] = source
            response = client.post("/api/estimate", json=payload)
            if response.status_code != 200:
                raise AssertionError(
                    f"{source}: {response.status_code} {response.text}"
                )
            body = response.json()
            assert body["recoverySource"] == source
            assert "successionProb" in body
            assert "recoveryProb" not in body
            assert 0 <= body["successionProb"] <= 1
            probabilities[source] = body["successionProb"]

        os.environ["KB_RECOVERY_SOURCE"] = "m2"
        candidates = []
        for floor, label in ((1, "같은 건물 1층"), (2, "같은 건물 2층")):
            candidate = {
                key: value
                for key, value in payload.items()
                if key != "uptae"
            }
            candidate.update(floor=floor, label=label)
            candidates.append(candidate)
        compare = client.post(
            "/api/compare",
            json={
                "uptae": uptae,
                "costParams": {
                    "opportunityRate": 0.07,
                    "horizonMonths": 24,
                },
                "candidates": candidates,
            },
        )
        assert compare.status_code == 200, compare.text
        compared = compare.json()
        assert compared["recoverySource"] == "m2"
        assert compared["paramsUsed"] == {
            "opportunityRate": 0.07,
            "horizonMonths": 24,
        }
        assert [item["label"] for item in compared["items"]] == [
            "같은 건물 1층",
            "같은 건물 2층",
        ]
        assert all(
            item["recoverySource"] == "m2"
            for item in compared["items"]
        )

        os.environ["KB_RECOVERY_SOURCE"] = "unsupported"
        unavailable = client.post("/api/estimate", json=payload)
        assert unavailable.status_code == 503

        properties = app.openapi()["components"]["schemas"][
            "EstimateResponse"
        ]["properties"]
        assert "successionProb" in properties
        assert "recoveryProb" not in properties
        assert "승계 확률" in properties["successionProb"]["description"]
    finally:
        if previous_source is None:
            os.environ.pop("KB_RECOVERY_SOURCE", None)
        else:
            os.environ["KB_RECOVERY_SOURCE"] = previous_source

    print(
        json.dumps(
            {
                "gridId": grid_id,
                "uptae": uptae,
                "estimateSources": probabilities,
                "compareSource": "m2",
                "paramsUsed": {
                    "opportunityRate": 0.07,
                    "horizonMonths": 24,
                },
                "labels": ["같은 건물 1층", "같은 건물 2층"],
                "invalidSourceStatus": 503,
                "openapiHasSuccessionProb": True,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
