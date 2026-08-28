"""금융 콘텐츠에 흔한 규모 단위(만/억/조 ↔ million/billion/trillion) 표현을
하나의 (raw_value, currency) 값으로 정규화하는 헬퍼.

$28 billion / 28 billion dollars / 280억 달러 는 모두 raw_value=2.8e10,
currency="USD"로 정규화되어 같은 값으로 취급된다. 반면 서로 다른 통화
(예: USD와 KRW)는 raw_value가 같아도 절대 같은 값으로 취급하지 않는다
- 통화 간 임의 환산은 하지 않는다는 원칙 때문이다. 본문에 통화가
명시되지 않은 경우(예: "250억"만 있고 "달러"/"원"이 없음)는
currency=None으로 남겨 두고, 호출하는 쪽(fact_validation.py)이 문맥
(MasterContent 안에 후보 통화가 하나뿐인지 여러 개인지)을 보고
PASS/REVIEW_REQUIRED를 판단한다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

KOREAN_SCALE_MULTIPLIERS: dict[str, int] = {
    "만": 10_000,
    "억": 100_000_000,
    "조": 1_000_000_000_000,
}
ENGLISH_SCALE_MULTIPLIERS: dict[str, int] = {
    "million": 1_000_000,
    "billion": 1_000_000_000,
    "trillion": 1_000_000_000_000,
}

_CURRENCY_ALIASES: dict[str, str] = {
    "달러": "USD",
    "dollar": "USD",
    "dollars": "USD",
    "usd": "USD",
    "$": "USD",
    "원": "KRW",
    "krw": "KRW",
    "₩": "KRW",
}

# 짧은 단위 필드(fact.unit)나 본문 조각 안에서 통화를 찾을 때 쓴다.
# "원"은 "원인"처럼 무관한 단어에도 등장할 수 있어 한글 앞뒤에 다른
# 한글 음절이 붙어 있지 않을 때만("원" 단독 또는 숫자/공백 뒤)만 잡는다.
_CURRENCY_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\$"), "USD"),
    (re.compile(r"달러"), "USD"),
    (re.compile(r"\bdollars?\b", re.IGNORECASE), "USD"),
    (re.compile(r"\busd\b", re.IGNORECASE), "USD"),
    (re.compile(r"₩"), "KRW"),
    (re.compile(r"(?<![가-힣])원(?![가-힣])"), "KRW"),
    (re.compile(r"\bkrw\b", re.IGNORECASE), "KRW"),
)


def normalize_currency_token(token: str | None) -> str | None:
    """통화를 나타내는 토큰(예: "달러", "USD", "dollars")을 표준 코드로 바꾼다.

    알 수 없는 토큰이나 None은 그대로 None을 돌려준다 - 통화를 임의로
    추정하지 않는다.
    """
    if not token:
        return None
    return _CURRENCY_ALIASES.get(token.strip().lower())


def detect_currency(text: str) -> str | None:
    """텍스트 조각 안에서 통화를 나타내는 표현을 찾아 표준 코드로 돌려준다.

    여러 통화가 함께 언급되어 있으면 먼저 매칭되는 것(USD 우선)을
    돌려준다 - fact.unit처럼 통화가 하나만 들어있는 짧은 필드를 위한
    용도다.
    """
    for pattern, code in _CURRENCY_PATTERNS:
        if pattern.search(text):
            return code
    return None


@dataclass(frozen=True)
class ScaledAmount:
    """규모 단위가 붙은 금액 하나.

    currency가 None이면 본문에 통화가 명시되지 않아 불명확하다는 뜻이다
    (임의로 특정 통화로 단정하지 않는다).
    """

    raw_value: float
    currency: str | None
    matched_text: str


_KOREAN_AMOUNT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(만|억|조)\s*(달러|원)?")
_ENGLISH_AMOUNT_RE = re.compile(
    r"\$?\s*(\d+(?:\.\d+)?)\s*(million|billion|trillion)\s*(dollars?|usd|원|krw)?",
    re.IGNORECASE,
)


def find_scaled_amounts(text: str) -> list[ScaledAmount]:
    """텍스트 안에서 "숫자 + 만/억/조/million/billion/trillion(+통화)"
    표현을 모두 찾아 raw_value(실제 금액)로 정규화한다.
    """
    results: list[ScaledAmount] = []

    for m in _KOREAN_AMOUNT_RE.finditer(text):
        number, scale, currency_token = m.groups()
        raw = float(number) * KOREAN_SCALE_MULTIPLIERS[scale]
        results.append(
            ScaledAmount(raw, normalize_currency_token(currency_token), m.group(0).strip())
        )

    for m in _ENGLISH_AMOUNT_RE.finditer(text):
        number, scale, currency_token = m.groups()
        raw = float(number) * ENGLISH_SCALE_MULTIPLIERS[scale.lower()]
        matched_text = m.group(0).strip()
        currency = "USD" if matched_text.startswith("$") else normalize_currency_token(currency_token)
        results.append(ScaledAmount(raw, currency, matched_text))

    return results


def scaled_amount_from_value_unit(value: float, unit: str) -> ScaledAmount | None:
    """Fact.value/Fact.unit처럼 구조화된 필드로부터 ScaledAmount를 만든다.

    unit에 규모 단위(만/억/조/million/billion/trillion)가 없으면(예: "%",
    "bp") None을 돌려준다 - 이 필드는 금액 규모 검사 대상이 아니라는
    뜻이다.
    """
    unit_lower = unit.lower()
    for word, multiplier in ENGLISH_SCALE_MULTIPLIERS.items():
        if word in unit_lower:
            return ScaledAmount(value * multiplier, detect_currency(unit), unit)
    for word, multiplier in KOREAN_SCALE_MULTIPLIERS.items():
        if word in unit:
            return ScaledAmount(value * multiplier, detect_currency(unit), unit)
    return None


def raw_values_equal(a: float, b: float) -> bool:
    """부동소수점 오차를 허용한 raw_value 비교."""
    return abs(a - b) < 1e-6 * max(1.0, abs(a), abs(b))


def classify_scaled_amount(found: ScaledAmount, allowed: list[ScaledAmount]) -> str:
    """found가 allowed(MasterContent에서 뽑은 금액들) 중 어떤 것과 맞는지
    "matched" / "review" / "unsupported" 중 하나로 분류한다.

    - raw_value가 일치하는 항목이 하나도 없으면 근거 없는 금액("unsupported").
    - raw_value는 일치하지만 통화가 서로 다르게 명시되어 있으면(예: found가
      "원"인데 allowed는 "달러"만 있음) 통화 자체가 다른 값이므로
      "unsupported"(임의 환산 금지).
    - found에 통화가 없고(예: "250억") raw_value가 일치하는 allowed 항목의
      통화가 전부 같으면(문맥상 하나뿐이면) "matched", 두 가지 이상이면
      불명확하므로 "review"(REVIEW_REQUIRED로 이어진다. FAIL로 막지
      않는다).
    """
    candidates = [a for a in allowed if raw_values_equal(a.raw_value, found.raw_value)]
    if not candidates:
        return "unsupported"

    if found.currency is not None:
        if any(a.currency == found.currency for a in candidates):
            return "matched"
        if any(a.currency is not None for a in candidates):
            return "unsupported"
        # 근거 쪽도 통화가 불명확했던 표현(예: macro_events의 "250억"처럼
        # 통화가 뒤에 따로 붙어 있던 경우)을 본문이 구체화한 것으로 본다.
        return "matched"

    if any(a.currency is None for a in candidates):
        return "matched"
    currencies = {a.currency for a in candidates}
    return "matched" if len(currencies) == 1 else "review"
