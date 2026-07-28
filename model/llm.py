"""LLM 호출 공용부 — 모델·재시도·실패 집계를 한 곳에서 정한다.

§16에서 실제로 난 사고: `except Exception: return None` 이 429를 성공적 무판정으로
처리해, 100초 동안 한 건도 저장되지 않는 동안에도 프로세스가 exit 0 으로 끝났다.
**측정 못 한 것은 측정 실패로 보고해야 한다.**

한도는 두 종류이고 대응이 다르다.
- **RPM/TPM** (분 단위) — 기다리면 풀린다. 백오프 재시도.
- **RPD** (일 단위) — 기다려도 오늘은 안 풀린다. 즉시 중단하고 위로 올린다.

`demand_run`·`absa_run`은 gpt-4o-mini 로 판정이 끝났고 결과가 §14~16에 기록됐다.
그쪽은 건드리지 않는다 — 판정 도구를 바꾸면 이미 난 판정의 근거가 흔들린다.
"""
import time
from collections import defaultdict

from pipeline.config import ENV_PATH

# §I-9·§I-11 판정 모델. gpt-4o-mini 는 RPD 10,000 을 소진했다(§16).
MODEL = "gpt-5.4-nano"
MAX_RETRY = 4


class DailyLimit(RuntimeError):
    """RPD 소진 또는 잔액 부족 — 재시도해도 안 풀린다."""


# 429 라고 다 같은 429가 아니다. 아래 문구가 들어오면 기다려도 안 풀리므로
# 백오프 재시도가 순수한 낭비다(호출당 7초 + 4회). 즉시 위로 올린다.
HARD_STOP = ("requests per day", "RPD", "insufficient_quota", "exceeded your current quota")


def load_key():
    env = {}
    for line in ENV_PATH.open(encoding="utf-8-sig"):
        s = line.strip()
        if s and not s.startswith("#") and "=" in s:
            k, v = s.split("=", 1)
            env[k.strip()] = v.strip()
    return env["OPENAI_API_KEY"]


def client():
    from openai import OpenAI
    return OpenAI(api_key=load_key())


def new_fails():
    return defaultdict(int)


def complete(cli, prompt, max_out, fails, model=MODEL):
    """JSON 문자열 또는 None. RPD 소진이면 DailyLimit 을 올린다.

    gpt-5.x 계열은 `max_tokens` 대신 `max_completion_tokens` 를 받고
    `temperature` 를 지원하지 않는다.
    """
    for attempt in range(MAX_RETRY):
        try:
            r = cli.chat.completions.create(
                model=model, max_completion_tokens=max_out,
                response_format={"type": "json_object"},
                messages=[{"role": "user", "content": prompt}])
            return r.choices[0].message.content
        except Exception as e:
            msg = str(e)
            if any(s in msg for s in HARD_STOP):
                raise DailyLimit(msg[:200])
            fails[type(e).__name__] += 1
            if attempt == MAX_RETRY - 1:
                return None
            time.sleep(2 ** attempt)      # 1 · 2 · 4초
    return None


def report(fails, saved, todo_n):
    """실패 요약을 찍고, 한 건도 못 건졌으면 True(=측정 실패)를 낸다."""
    if fails:
        print("  실패 " + " · ".join(f"{k} {v:,}" for k, v in
                                    sorted(fails.items(), key=lambda kv: -kv[1])))
    if todo_n and saved == 0:
        print(f"  한 건도 저장하지 못했다 — 측정 실패 (대상 {todo_n:,}건)")
        return True
    return False
