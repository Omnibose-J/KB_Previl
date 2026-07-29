"""LLM evidence sentences with a strict numeric whitelist."""

import json
import re
from typing import Annotated

from openai import OpenAI, OpenAIError
from pydantic import BaseModel, Field

from pipeline.config import load_env
from service import api


REPORT_MODEL = "gpt-5.4-mini"

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
    except OpenAIError as exc:
        raise ReportUnavailableError(
            f"OpenAI 보고서 생성 호출이 실패했습니다: {type(exc).__name__}"
        ) from exc

    message = completion.choices[0].message
    if getattr(message, "refusal", None):
        raise ReportGenerationError("OpenAI가 보고서 생성을 거부했습니다.")
    if message.parsed is None:
        raise ReportGenerationError("구조화된 보고서 응답을 받지 못했습니다.")
    reject_non_korean(message.parsed.sentences)
    return message.parsed.sentences


REPORT_ATTEMPTS = 2


def _generate_verified(evidence):
    """가드에 걸리면 한 번 더 받아 본다.

    모델 출력은 확률적이라 같은 입력에도 다음 시도가 통과하는 경우가 많다
    (실측: 후보 3곳 중 1곳이 «3년»의 3 을 placeholder 없이 직접 써서 숫자
    가드에 걸렸다). 두 번 다 실패하면 그대로 올린다 — 가드를 느슨하게 풀어
    통과시키는 것보다 502 가 낫다. 화면은 근거 없는 문장을 실을 바에야
    아무것도 안 싣는 쪽이다.

    ReportUnavailableError(키 없음·API 장애)는 잡지 않는다. 다시 물어봐야
    같은 답이고, 재시도는 장애를 늦게 알리는 것 말고는 하는 일이 없다.
    """
    failure = None
    for _ in range(REPORT_ATTEMPTS):
        try:
            generated = _generate_sentences(evidence)
            return render_evidence_placeholders(generated, evidence)
        except ReportGenerationError as exc:
            failure = exc
    raise failure


def generate(grid_id, uptae):
    evidence, observed_survival = _report_context(grid_id, uptae)
    sentences = _generate_verified(evidence)
    return {
        "grid_id": grid_id,
        "uptae": uptae,
        "sentences": [*sentences, _risk_caveat(observed_survival)],
    }
