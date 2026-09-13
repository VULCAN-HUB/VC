"""EB 프로토콜 v0.1 메시지 정의 (protocol.md 참조).

폰과 PC가 주고받는 JSON의 형태를 한 곳에 모아둔다. 여기가 유일한 기준이고,
나중에 코틀린 쪽을 만들 때도 이 파일을 보고 맞춘다.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

PROTOCOL_VERSION = "0.1"

Phase = Literal[
    "instruction_start",
    "intent",
    "module_select",
    "module_run",
    "render",
    "intervention",
    "done",
]
Tier = Literal["phone", "pc", "api"]
Outcome = Literal[
    "success", "failure", "clarified", "cancelled", "accepted", "ignored", "blocked"
]
ProposalType = Literal["skill_proposal", "skill_update", "intervention_proposal"]
Decision = Literal["approve", "reject", "revert"]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


@dataclass
class Hello:
    """GET /eb/v1/hello — 폰이 PC를 2단으로 쓸 수 있는지 판단하는 근거."""

    models: list[str]
    capabilities: list[str]
    busy: bool = False
    protocol: str = PROTOCOL_VERSION


@dataclass
class LogEvent:
    """POST /eb/v1/log — 지시 시작 시점부터 이벤트 단위로 흘려보낸다.

    계측 필드(latency_ms, tokens, cost, retries)는 처음부터 넣는다. 성공한 지시를
    최적화하려면 비교할 숫자가 있어야 하고, 계측은 나중에 붙일 수 없다.
    """

    instruction_id: str
    seq: int
    phase: Phase
    tier: Tier
    outcome: Outcome
    ts: str = field(default_factory=now_iso)
    module: str | None = None
    step: str | None = None
    latency_ms: int | None = None
    tokens_in: int | None = None
    tokens_out: int | None = None
    cost_krw: float = 0.0
    retries: int = 0
    clarify_count: int = 0
    failure_point: str | None = None
    detail: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # ★★ **정해진 이름 밖의 값은 받지 않는다.** `Literal` 은 적어 두기만 할 뿐 막지 않아서
        #   `outcome: "성공"` · `tier: "gpu"` 가 그대로 저장됐고, 분석은 `failure` 만 세므로 **학습 재료가 말없이 빠졌다.**
        #   숫자 칸에 글자가 와도 그대로 들어갔다. 폰이 한 글자만 틀려도 이렇게 된다 — 문에서 400 으로 돌려준다.
        from typing import get_args

        for 칸, 틀 in (("phase", Phase), ("tier", Tier), ("outcome", Outcome)):
            if getattr(self, 칸) not in get_args(틀):
                raise ValueError(f"{칸} 은 {'·'.join(get_args(틀))} 중 하나다: {getattr(self, 칸)!r}")
        for 칸 in ("seq", "retries", "clarify_count", "latency_ms", "tokens_in", "tokens_out"):
            값 = getattr(self, 칸)
            if (값 is not None or 칸 in ("seq", "retries", "clarify_count")) and (
                    isinstance(값, bool) or not isinstance(값, int)):
                raise ValueError(f"{칸} 은 정수다: {값!r}")
        if isinstance(self.cost_krw, bool) or not isinstance(self.cost_krw, (int, float)):
            raise ValueError(f"cost_krw 는 숫자다: {self.cost_krw!r}")
        for 칸 in ("instruction_id", "ts", "module", "step", "failure_point"):
            값 = getattr(self, 칸)
            if 값 is not None and not isinstance(값, str):
                raise ValueError(f"{칸} 은 글자다: {값!r}")
        if not isinstance(self.detail, dict):
            raise ValueError(f"detail 은 객체다: {self.detail!r}")
        # 실패인데 어디서 막혔는지 없으면 학습 재료가 못 된다(결정 17·24).
        if self.outcome == "failure" and not self.failure_point:
            raise ValueError("failure 이벤트에는 failure_point가 있어야 한다")
        if self.outcome != "failure" and self.failure_point:
            raise ValueError("실패가 아닌데 failure_point가 있다")


@dataclass
class Proposal:
    """PC → 폰. 자동 적용은 없다. 사용자 승인을 거쳐야 활성화된다(결정 18)."""

    proposal_id: str
    type: ProposalType
    title: str
    summary: str
    based_on: list[str] = field(default_factory=list)
    declaration: dict[str, Any] = field(default_factory=dict)


@dataclass
class ProposalDecision:
    """POST /eb/v1/proposals/{id}/decision"""

    decision: Decision


def dumps(msg: Any) -> str:
    return json.dumps(asdict(msg), ensure_ascii=False)


def loads(cls: type, raw: str):
    return cls(**json.loads(raw))


def _self_check() -> None:
    hello = loads(Hello, dumps(Hello(models=["m"], capabilities=["inference"])))
    assert hello.protocol == PROTOCOL_VERSION
    assert hello.busy is False

    ok = LogEvent(
        instruction_id="01J",
        seq=1,
        phase="module_run",
        tier="pc",
        outcome="success",
        latency_ms=820,
    )
    assert loads(LogEvent, dumps(ok)).latency_ms == 820
    assert ok.ts.endswith("Z")

    bad = LogEvent(
        instruction_id="01J",
        seq=2,
        phase="module_run",
        tier="api",
        outcome="failure",
        failure_point="vision_query",
    )
    assert loads(LogEvent, dumps(bad)).failure_point == "vision_query"

    for kwargs in (
        dict(outcome="failure", failure_point=None),
        dict(outcome="success", failure_point="vision_query"),
        # ★ 정해진 이름·꼴 밖의 값 — 전엔 그대로 저장돼 분석에서 말없이 빠졌다
        dict(outcome="성공"),
        dict(outcome="success", tier_="gpu"),
        dict(outcome="success", latency_ms="820"),
        dict(outcome="success", retries=True),
        dict(outcome="success", detail=[]),
        dict(outcome="success", module=5),
    ):
        if "tier_" in kwargs:
            kwargs = {**{k: v for k, v in kwargs.items() if k != "tier_"}}
            try:
                LogEvent(instruction_id="01J", seq=3, phase="module_run", tier="gpu", **kwargs)
            except ValueError:
                continue
            raise AssertionError("tier 가 정해진 이름 밖인데 통과했다")
        try:
            LogEvent(
                instruction_id="01J", seq=3, phase="module_run", tier="pc", **kwargs
            )
        except ValueError:
            pass
        else:
            raise AssertionError(f"검증이 통과하면 안 된다: {kwargs}")

    p = loads(
        Proposal,
        dumps(Proposal(proposal_id="01J", type="skill_proposal", title="출근 준비", summary="아침 브리핑")),
    )
    assert p.title == "출근 준비"
    assert loads(ProposalDecision, dumps(ProposalDecision(decision="revert"))).decision == "revert"

    print("self-check 통과")


if __name__ == "__main__":
    _self_check()
