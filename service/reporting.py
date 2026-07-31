"""LLM evidence sentences with a strict numeric whitelist."""

import json
import re
import time
from typing import Annotated

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
# 한국어 문장에 한자는 섞이지 않는다. 추론 흔적이 새면 여기로 나타난다("重新").
_HANJA = re.compile(r"[㐀-䶿一-鿿]")
_HANGUL = re.compile(r"[가-힣]")
# 라틴 문자는 통째로 막을 수 없다 — evidence 값이 맨 숫자라 단위(m, km)는
# 모델이 붙여야 하고, 그건 정상 문장이다. 대신 «영어 낱말»의 길이로 가른다.
# 단위·약어는 3자 이하(m, km, AI, LLM)이고, 새어 나온 영어는 그보다 길다
# (Need, schema, Station, because). 총량도 함께 본다 — 짧은 낱말을 여러 개
# 늘어놓는 경우가 있다.
_LATIN_RUN = re.compile(r"[A-Za-z]+")
_MAX_LATIN_RUN = 3
_MAX_LATIN_TOTAL = 8
_NUMBER_TOKEN = re.compile(
    r"(?<![0-9A-Za-z.])[+-]?(?:\d+(?:,\d{3})*(?:\.\d+)?|\.\d+)"
    r"(?:[eE][+-]?\d+)?"
)
_NUMERIC_OPERATOR = re.compile(r"^[\s+\-−*/×÷^%∕⁄~～]+$")


class ReportUnavailableError(RuntimeError):
    """The configured LLM service is unavailable."""


class ReportGenerationError(RuntimeError):
    """The LLM response did not satisfy the public report contract."""


class NonKoreanSentenceError(ReportGenerationError):
    def __init__(self, sentence):
        self.sentence = sentence
        super().__init__(
            "LLM 응답이 한국어 근거 문장이 아닙니다: " + sentence[:80]
        )


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


# 값이 내부 enum 이라 문장에 그대로 실리면 뜻이 통하지 않는 키. confidence 는
# "full"/"partial" 로 오는데, 모델이 «분석 기준은 full 로 제시되었습니다» 처럼
# 인용해 영어 낱말이 화면까지 나갔다. 화면은 이 값을 따로 자기 방식으로 쓴다.
_NOT_QUOTABLE = frozenset({"confidence"})


def quotable_evidence(evidence):
    """placeholder 로 인용할 수 있는 항목만 남긴다.

    인용은 문자열 값에만 성립한다 — 리스트를 문장 가운데 넣을 방법이 없다.
    모델에게 주는 payload 와 인용 허용 집합이 같아야 한다. 다르면 모델은
    자기가 본 키를 정직하게 인용했는데 «알 수 없는 placeholder» 로 거부당한다
    (실제로 missingAxes 가 리스트라 그렇게 502 가 났다).
    """
    return {
        key: value
        for key, value in evidence.items()
        if isinstance(value, str) and key not in _NOT_QUOTABLE
    }


def render_evidence_placeholders(sentences, evidence):
    generated_text = "\n".join(sentences)
    numeric_glyphs = {
        character for character in generated_text if character.isnumeric()
    }
    if numeric_glyphs:
        raise UnapprovedNumberError(numeric_glyphs)

    scalar_evidence = quotable_evidence(evidence)
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


def reject_non_korean(sentences):
    """모델의 사고 흔적이 문장 칸으로 새는 것을 형태로 막는다.

    Structured Outputs 는 JSON 의 «모양»만 보장한다 — sentences 가 문자열
    2~4개이기만 하면 그 안에 무엇이 들어 있든 파싱은 통과한다. 숫자 화이트
    리스트도 숫자가 없는 텍스트는 잡지 못해서, 실제로 «Need final exact
    schema ... 重新» 이 화면까지 나갔다.

    placeholder 를 걷어낸 나머지는 한국어여야 한다. 단위(m, km)는 evidence 가
    맨 숫자로 오기 때문에 모델이 붙이는 것이 맞으므로, 라틴 문자를 통째로
    막지 않고 낱말 길이와 총량으로 가른다.
    """
    for sentence in sentences:
        body = _PLACEHOLDER.sub("", sentence)
        runs = _LATIN_RUN.findall(body)
        if (
            not _HANGUL.search(body)
            or _HANJA.search(body)
            or any(len(run) > _MAX_LATIN_RUN for run in runs)
            or sum(len(run) for run in runs) > _MAX_LATIN_TOTAL
        ):
            raise NonKoreanSentenceError(sentence)


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
                        # 인용 가능한 항목만 보낸다. 인용 못 하는 키를 보여 주면
                        # 모델은 그것도 근거로 알고 인용하고, 그 순간 거부당한다.
                        "content": json.dumps(
                            quotable_evidence(evidence),
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
    reject_non_korean(message.parsed.sentences)
    return message.parsed.sentences


def _generate_verified(evidence):
    """Reject an invalid model response without asking the model to replace it.

    Retries belong only to transient call failures in `_request_completion`.
    Numeric, placeholder, and language violations are contract failures, so a
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
