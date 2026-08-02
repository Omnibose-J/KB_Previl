"""LLM-selected evidence rendered through server-owned sentences."""

import json
import re
import time
from typing import Literal

import httpx
from openai import AuthenticationError, OpenAI, OpenAIError, RateLimitError
from pydantic import BaseModel, Field

from pipeline.config import load_env
from service import api


REPORT_MODEL = "gpt-5.4-mini"
REPORT_CALL_ATTEMPTS = 4
_REPORT_BACKOFF_BASE_SECONDS = 2.0
_REPORT_BACKOFF_CAP_SECONDS = 29.0
_TRANSIENT_RATE_LIMIT_CODES = frozenset({"rate_limit_exceeded"})
_QUOTA_ERROR_CODES = frozenset({
    "insufficient_quota",
    "credit_balance_exhausted",
    "billing_hard_limit_reached",
    "organization_spend_limit_exceeded",
    "project_spend_limit_exceeded",
    "organization_usage_limit_exceeded",
})
_REPORT_TEMPORARY_DETAIL = (
    "OpenAI 보고서 생성이 일시적으로 막혔습니다. 잠시 후 다시 시도해 주세요."
)
_REPORT_ACCOUNT_DETAIL = (
    "OpenAI API 키가 없거나 사용 가능 잔액이 없습니다. "
    "설정 또는 결제 상태를 확인해 주세요."
)
_REPORT_OTHER_DETAIL = (
    "OpenAI 보고서 생성 호출에 실패했습니다. 서비스 설정과 상태를 확인해 주세요."
)

_PLACEHOLDER = re.compile(r"\{\{([A-Za-z][A-Za-z0-9]*)\}\}")

GRADE_SURVIVAL_SENTENCE = (
    "이 자리는 {{grade}}등급이고, 같은 등급의 {{horizonYears}}년 실측 생존율은 "
    "{{observedSurvivalPercent}}%예요."
)
LOCAL_COMPETITION_SENTENCE = (
    "이 격자에는 음식점 {{shopsHere}}곳, 주변 격자 범위에는 "
    "{{shopsNeighbor}}곳이 있어요."
)
TURNOVER_SENTENCE = (
    "누적 개업 기록은 {{openingsTotal}}곳, 폐업 기록은 {{closuresTotal}}곳이에요."
)
AREA_SURVIVAL_SENTENCE = (
    "이 상권의 실측 생존율은 {{areaSurvivalPercent}}%이고, "
    "표본은 {{areaSurvivalSample}}곳이에요."
)
STATION_ACCESS_SENTENCE = (
    "가장 가까운 역은 {{stationName}}이고, 거리는 약 "
    "{{stationDistanceMeters}}m예요."
)
LOCATION_SENTENCE = "{{district}} {{administrativeDong}}에 있는 자리예요."

ReportSentence = Literal[
    GRADE_SURVIVAL_SENTENCE,
    LOCAL_COMPETITION_SENTENCE,
    TURNOVER_SENTENCE,
    AREA_SURVIVAL_SENTENCE,
    STATION_ACCESS_SENTENCE,
    LOCATION_SENTENCE,
]

_SENTENCE_REQUIREMENTS = {
    GRADE_SURVIVAL_SENTENCE: (
        "grade",
        "horizonYears",
        "observedSurvivalPercent",
    ),
    LOCAL_COMPETITION_SENTENCE: ("shopsHere", "shopsNeighbor"),
    TURNOVER_SENTENCE: ("openingsTotal", "closuresTotal"),
    AREA_SURVIVAL_SENTENCE: ("areaSurvivalPercent", "areaSurvivalSample"),
    STATION_ACCESS_SENTENCE: ("stationName", "stationDistanceMeters"),
    LOCATION_SENTENCE: ("district", "administrativeDong"),
}
_REPORT_EVIDENCE_KEYS = frozenset(
    key for requirements in _SENTENCE_REQUIREMENTS.values() for key in requirements
)


class ReportUnavailableError(RuntimeError):
    """The configured LLM service is unavailable."""


class ReportGenerationError(RuntimeError):
    """The LLM response did not satisfy the public report contract."""


class GeneratedReport(BaseModel):
    sentences: list[ReportSentence] = Field(min_length=2, max_length=4)


def _format(value, digits=None):
    if value is None:
        return None
    if digits is None:
        return str(value)
    return f"{value:.{digits}f}"


def _report_context(grid_id, uptae):
    detail = api.grid_detail(grid_id, uptae)
    if detail is None:
        raise api.ResourceNotFoundError(api.NOT_EVALUATED_DETAIL)
    metadata = api.meta()

    evidence = {
        "grade": _format(detail["grade"]),
        "observedSurvivalPercent": _format(detail["observed_survival"] * 100, 1),
        "overallSurvivalPercent": _format(
            (
                metadata["overall_survival"] * 100
                if metadata["overall_survival"] is not None
                else None
            ),
            1,
        ),
        "horizonYears": "3",
        "confidence": detail["confidence"],
        "district": detail["district"],
        "administrativeDong": detail["adm_dong"],
        "shopsHere": _format(detail["competition"]["shops_here"]),
        "shopsNeighbor": _format(detail["competition"]["shops_neighbor"]),
        "openingsTotal": _format(detail["competition"]["openings_total"]),
        "closuresTotal": _format(detail["competition"]["closures_total"]),
        "areaSurvivalPercent": _format(
            (
                detail["area_survival"]["rate"] * 100
                if detail["area_survival"]["rate"] is not None
                else None
            ),
            1,
        ),
        "areaSurvivalSample": _format(detail["area_survival"]["sample"]),
        "stationName": (
            detail["nearest_station"]["name"] if detail["nearest_station"] else None
        ),
        "stationDistanceMeters": _format(
            (
                round(detail["nearest_station"]["distance_m"])
                if detail["nearest_station"]
                and detail["nearest_station"]["distance_m"] is not None
                else None
            )
        ),
        "missingAxes": detail["missing_axes"],
    }
    return (
        {key: value for key, value in evidence.items() if value is not None},
        detail["observed_survival"],
    )


def build_evidence(grid_id, uptae):
    evidence, _observed_survival = _report_context(grid_id, uptae)
    return evidence


def _risk_caveat(observed_survival):
    if observed_survival is None or not 0 <= observed_survival <= 1:
        raise ReportGenerationError("격자 실측 생존율이 유효하지 않습니다.")
    closure_percent = round((1 - observed_survival) * 100)
    return (
        "이 등급 자리에서도 3년 안에 "
        f"약 {closure_percent}%가 문을 닫았어요. "
        "등급은 참고이지 잘된다는 보장은 아니에요."
    )


def quotable_evidence(evidence):
    """Return only scalar evidence used by a server-owned sentence."""
    return {
        key: value
        for key, value in evidence.items()
        if isinstance(value, str) and key in _REPORT_EVIDENCE_KEYS
    }


def eligible_report_sentences(evidence):
    scalar_evidence = quotable_evidence(evidence)
    return [
        sentence
        for sentence, requirements in _SENTENCE_REQUIREMENTS.items()
        if all(key in scalar_evidence for key in requirements)
    ]


def render_evidence_placeholders(sentences, evidence):
    if not 2 <= len(sentences) <= 4:
        raise ReportGenerationError("보고서 근거 문장은 2~4개여야 합니다.")
    if len(sentences) != len(set(sentences)):
        raise ReportGenerationError("보고서 근거 문장은 중복될 수 없습니다.")

    scalar_evidence = quotable_evidence(evidence)
    for sentence in sentences:
        requirements = _SENTENCE_REQUIREMENTS.get(sentence)
        if requirements is None:
            raise ReportGenerationError(
                "LLM 응답에 허용되지 않은 근거 문장이 포함됐습니다."
            )
        missing = [key for key in requirements if key not in scalar_evidence]
        if missing:
            raise ReportGenerationError(
                "LLM 응답이 없는 근거를 선택했습니다: " + ", ".join(missing)
            )

    return [
        _PLACEHOLDER.sub(
            lambda match: scalar_evidence[match.group(1)],
            sentence,
        )
        for sentence in sentences
    ]


def _openai_error_codes(exc):
    values = {
        getattr(exc, "code", None),
        getattr(exc, "type", None),
    }
    body = getattr(exc, "body", None)
    if isinstance(body, dict):
        error = body.get("error", body)
        if isinstance(error, dict):
            values.update({error.get("code"), error.get("type")})
    return values - {None}


def _request_completion(client, evidence):
    for attempt in range(REPORT_CALL_ATTEMPTS):
        try:
            return client.beta.chat.completions.parse(
                model=REPORT_MODEL,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "당신은 서울 요식업 입지 리포트의 근거 선택자입니다. "
                            "eligibleSentences에서 서로 다른 문장 2~4개를 그대로 "
                            "고르세요. 문장을 수정하거나 새로 작성하지 마세요."
                        ),
                    },
                    {
                        "role": "user",
                        "content": json.dumps(
                            {
                                "evidence": quotable_evidence(evidence),
                                "eligibleSentences": eligible_report_sentences(evidence),
                            },
                            ensure_ascii=False,
                            sort_keys=True,
                        ),
                    },
                ],
                response_format=GeneratedReport,
            )
        except RateLimitError as exc:
            error_codes = _openai_error_codes(exc)
            if error_codes & _QUOTA_ERROR_CODES:
                raise ReportUnavailableError(_REPORT_ACCOUNT_DETAIL) from exc
            if not error_codes & _TRANSIENT_RATE_LIMIT_CODES:
                raise ReportUnavailableError(_REPORT_OTHER_DETAIL) from exc
            if attempt == REPORT_CALL_ATTEMPTS - 1:
                raise ReportUnavailableError(_REPORT_TEMPORARY_DETAIL) from exc
            delay = min(
                _REPORT_BACKOFF_CAP_SECONDS,
                _REPORT_BACKOFF_BASE_SECONDS * (2 ** attempt),
            )
            time.sleep(delay)
        except AuthenticationError as exc:
            raise ReportUnavailableError(_REPORT_ACCOUNT_DETAIL) from exc
        except OpenAIError as exc:
            raise ReportUnavailableError(_REPORT_OTHER_DETAIL) from exc


def _generate_sentences(evidence):
    if len(eligible_report_sentences(evidence)) < 2:
        raise ReportGenerationError("보고서를 구성할 근거가 2개보다 적습니다.")
    try:
        api_key = load_env().get("OPENAI_API_KEY")
    except (OSError, UnicodeError) as exc:
        raise ReportUnavailableError(_REPORT_ACCOUNT_DETAIL) from exc
    if not api_key:
        raise ReportUnavailableError(_REPORT_ACCOUNT_DETAIL)

    client = OpenAI(
        api_key=api_key,
        # Connect 5s, read 30s. Offline (the 본선 demo runs with no network) the
        # connect stage is what fails, so a single timeout of 30 would freeze the
        # card for 30 seconds before showing its error. Generation itself can be
        # slow and keeps the full budget.
        timeout=httpx.Timeout(30.0, connect=5.0),
        # The SDK retries every 429 alike. We have to see the first response to
        # distinguish transient rate limits from non-retryable quota failures.
        max_retries=0,
    )
    completion = _request_completion(client, evidence)

    message = completion.choices[0].message
    if getattr(message, "refusal", None):
        raise ReportGenerationError("OpenAI가 보고서 생성을 거부했습니다.")
    if message.parsed is None:
        raise ReportGenerationError("구조화된 보고서 응답을 받지 못했습니다.")
    return message.parsed.sentences


def _generate_verified(evidence):
    """Reject an invalid model response without asking the model to replace it.

    Retries belong only to transient call failures in `_request_completion`.
    Unsupported or unavailable sentence selections are contract failures, so a
    second generated answer must not hide the first rejected response.
    """
    generated = _generate_sentences(evidence)
    return render_evidence_placeholders(generated, evidence)


def generate(grid_id, uptae):
    evidence, observed_survival = _report_context(grid_id, uptae)
    sentences = _generate_verified(evidence)
    return {
        "grid_id": grid_id,
        "uptae": uptae,
        "sentences": [*sentences, _risk_caveat(observed_survival)],
    }
