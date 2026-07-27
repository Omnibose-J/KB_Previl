"""LLM evidence sentences with a strict numeric whitelist."""

import json
import re
from typing import Annotated

from openai import OpenAI, OpenAIError
from pydantic import BaseModel, Field

from pipeline.config import load_env
from service import api


REPORT_MODEL = "gpt-5.6"

_PLACEHOLDER = re.compile(r"\{\{([A-Za-z][A-Za-z0-9]*)\}\}")
_NUMBER_TOKEN = re.compile(
    r"(?<![0-9A-Za-z.])[+-]?(?:\d+(?:,\d{3})*(?:\.\d+)?|\.\d+)"
    r"(?:[eE][+-]?\d+)?"
)
_NUMERIC_OPERATOR = re.compile(r"^[\s+\-−*/×÷^%∕⁄~～]+$")


class ReportUnavailableError(RuntimeError):
    """The configured LLM service is unavailable."""


class ReportGenerationError(RuntimeError):
    """The LLM response did not satisfy the public report contract."""


class UnapprovedNumberError(ReportGenerationError):
    def __init__(self, numbers):
        self.numbers = sorted(numbers)
        super().__init__(
            "LLM 응답에 근거 payload에 없는 숫자가 포함됐습니다: "
            + ", ".join(self.numbers)
        )


class GeneratedReport(BaseModel):
    sentences: list[Annotated[str, Field(min_length=1, max_length=240)]] = Field(
        min_length=2, max_length=4
    )


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
        "이 등급 자리의 실측 3년 내 폐업률은 "
        f"약 {closure_percent}%입니다. "
        "등급은 입지의 확률이지 성패의 보증이 아닙니다."
    )


def render_evidence_placeholders(sentences, evidence):
    generated_text = "\n".join(sentences)
    numeric_glyphs = {
        character for character in generated_text if character.isnumeric()
    }
    if numeric_glyphs:
        raise UnapprovedNumberError(numeric_glyphs)

    scalar_evidence = {
        key: value for key, value in evidence.items() if isinstance(value, str)
    }
    placeholders = set(_PLACEHOLDER.findall(generated_text))
    unknown = placeholders - set(scalar_evidence)
    if unknown:
        raise ReportGenerationError(
            "LLM 응답에 알 수 없는 evidence placeholder가 포함됐습니다: "
            + ", ".join(sorted(unknown))
        )

    without_placeholders = _PLACEHOLDER.sub("", generated_text)
    if "{{" in without_placeholders or "}}" in without_placeholders:
        raise ReportGenerationError(
            "LLM 응답의 evidence placeholder 형식이 잘못됐습니다."
        )

    matches = list(_PLACEHOLDER.finditer(generated_text))
    for previous, current in zip(matches, matches[1:]):
        previous_value = scalar_evidence[previous.group(1)]
        current_value = scalar_evidence[current.group(1)]
        if not (
            _NUMBER_TOKEN.search(previous_value) and _NUMBER_TOKEN.search(current_value)
        ):
            continue
        bridge = generated_text[previous.end() : current.start()]
        if bridge == "" or _NUMERIC_OPERATOR.fullmatch(bridge):
            raise ReportGenerationError(
                "숫자 evidence placeholder를 결합하거나 계산할 수 없습니다."
            )

    rendered = [
        _PLACEHOLDER.sub(
            lambda match: scalar_evidence[match.group(1)],
            sentence,
        )
        for sentence in sentences
    ]
    allowed_numbers = {
        match.group(0)
        for value in scalar_evidence.values()
        for match in _NUMBER_TOKEN.finditer(value)
    }
    rendered_numbers = {
        match.group(0)
        for sentence in rendered
        for match in _NUMBER_TOKEN.finditer(sentence)
    }
    unapproved = rendered_numbers - allowed_numbers
    if unapproved:
        raise UnapprovedNumberError(unapproved)
    return rendered


def _generate_sentences(evidence):
    try:
        api_key = load_env().get("OPENAI_API_KEY")
    except (OSError, UnicodeError) as exc:
        raise ReportUnavailableError(
            f"OpenAI 설정을 읽지 못했습니다: {type(exc).__name__}"
        ) from exc
    if not api_key:
        raise ReportUnavailableError("OPENAI_API_KEY가 설정되지 않았습니다.")

    client = OpenAI(
        api_key=api_key,
        timeout=30.0,
        max_retries=1,
    )
    try:
        completion = client.beta.chat.completions.parse(
            model=REPORT_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "당신은 서울 요식업 입지 리포트 작성자입니다. "
                        "JSON 근거만 사용해 짧은 한국어 근거 문장을 작성하세요. "
                        "근거 값을 인용할 때는 JSON key를 {{grade}}처럼 "
                        "중괄호 2개의 placeholder로만 쓰세요. "
                        "숫자 글리프를 직접 쓰거나 계산하거나 반올림하지 마세요. "
                        "인과관계나 성공 보장을 주장하지 마세요."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        evidence,
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                },
            ],
            response_format=GeneratedReport,
        )
    except OpenAIError as exc:
        raise ReportUnavailableError(
            f"OpenAI 보고서 생성 호출이 실패했습니다: {type(exc).__name__}"
        ) from exc

    message = completion.choices[0].message
    if getattr(message, "refusal", None):
        raise ReportGenerationError("OpenAI가 보고서 생성을 거부했습니다.")
    if message.parsed is None:
        raise ReportGenerationError("구조화된 보고서 응답을 받지 못했습니다.")
    return message.parsed.sentences


def generate(grid_id, uptae):
    evidence, observed_survival = _report_context(grid_id, uptae)
    generated = _generate_sentences(evidence)
    sentences = render_evidence_placeholders(generated, evidence)
    return {
        "grid_id": grid_id,
        "uptae": uptae,
        "sentences": [*sentences, _risk_caveat(observed_survival)],
    }
