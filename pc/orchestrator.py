"""VC 오케스트레이터 코어 — 지시 하나가 흐르는 전 경로.

    VC(호출어) → STT → 의도 분석 → 모듈 선택 → 입력 수집 → 처리 단계 결정 → 렌더

**이 파일은 폰(Kotlin)으로 이식될 참조 구현이다**(결정 25: 본체는 폰). 지금 파이썬으로 두는
이유는 폰 없이 PC에서 전 경로를 돌려보기 위해서다(결정 26). 이식할 때 그대로 옮길 수 있도록
플랫폼 의존 코드를 넣지 않는다 — 카메라·마이크·HUD는 전부 바깥에서 주입받는다.

담는 결정:

- 결정 10  모듈 계약: 모듈이 자기 의도·입력·처리 단계·렌더 형식을 선언한다
- 결정 11  모듈 선택: 트리거 규칙 → 소형 모델 → 모호하면 되묻는다
- 결정 5   처리 단계는 작업 종류 고정 매핑(모듈이 선언)
- 결정 21  전경 1 + 배경 N, 배경의 중요 알림은 뚫고 올라온다
- 결정 24  실패하면 상위 단계로 1회 승격 후 보고
- 결정 17  지시 시작 시점부터 계측과 함께 로그를 흘려보낸다
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field, replace
from typing import Any, Callable, Protocol

from eb_protocol import LogEvent, Tier

TIER_ORDER: list[Tier] = ["phone", "pc", "api"]


class Brain(Protocol):
    """모델 접근. 폰에서는 1단 온디바이스 모델, PC·API는 결정 3의 어댑터가 채운다."""

    def classify(self, text: str, choices: list[str]) -> str | None: ...


@dataclass
class ModuleSpec:
    """모듈 계약(결정 10). 새 모듈은 이 선언만 채우면 오케스트레이터가 알아서 부른다."""

    name: str
    triggers: list[str]
    run: Callable[["Instruction"], str]
    tiers: list[Tier] = field(default_factory=lambda: ["phone"])
    needs: list[str] = field(default_factory=list)  # camera, mic, location, sensors
    render: str = "card"  # card | overlay | voice
    persistent: bool = False  # 지속형이면 배경에서 계속 돈다(결정 21)
    can_interrupt: bool = False  # 배경에서도 전경을 뚫고 알릴 수 있는가(결정 21)

    def matches(self, text: str) -> bool:
        return any(t in text for t in self.triggers)


@dataclass
class Instruction:
    """지시 하나의 수명. 계측이 여기 붙는다(결정 17)."""

    text: str
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:16])
    seq: int = 0
    module: str | None = None
    tier: Tier = "phone"
    retries: int = 0
    clarify_count: int = 0
    started: float = field(default_factory=time.perf_counter)
    context: dict[str, Any] = field(default_factory=dict)

    def next_seq(self) -> int:
        self.seq += 1
        return self.seq


class ModuleFailed(RuntimeError):
    """모듈이 이 단계에서 못 했다. 오케스트레이터가 승격할지 정한다(결정 24)."""

    def __init__(self, where: str, detail: str = "") -> None:
        super().__init__(detail or where)
        self.where = where


@dataclass
class Reply:
    """사용자에게 돌려주는 것. HUD 렌더 계층이 이걸 받는다."""

    text: str
    kind: str = "result"  # result | clarify | failure | ambient
    module: str | None = None
    render: str = "card"


class Orchestrator:
    def __init__(
        self,
        modules: list[ModuleSpec],
        brain: Brain | None = None,
        log: Callable[[LogEvent], None] | None = None,
    ) -> None:
        self.base_modules = {m.name: m for m in modules}
        self.modules = dict(self.base_modules)
        self.brain = brain
        self.log = log or (lambda e: None)
        self.background: list[Instruction] = []

    # --- 학습 결과 반영 (결정 17) ---------------------------------------

    def load_skills(self, skills: list[Any]) -> None:
        """승인된 스킬을 실제 동작에 반영한다. 여기가 학습 루프의 마지막 고리다.

        스킬은 데이터라서 적용도 데이터를 갈아 끼우는 것으로 끝난다. 코드를 생성하거나
        실행하지 않는다(결정 17: 폰에서 자동 생성 코드를 실행하지 않는다).

        다시 부를 수 있도록 매번 원본에서 새로 만든다 — 되돌리기가 그냥 다시 부르는 것이 된다.
        """
        self.modules = dict(self.base_modules)
        self.skills = list(skills)
        for skill in skills:
            steps = getattr(skill, "steps", None) or []
            target = self.base_modules.get(skill.name)

            if target is not None:
                # 기존 모듈을 손본다. 낭비 감지가 만든 start_tier가 여기로 들어온다.
                patched = replace(target)
                if skill.start_tier:
                    start = TIER_ORDER.index(skill.start_tier)
                    patched.tiers = [t for t in TIER_ORDER[start:] if t in target.tiers] or [
                        skill.start_tier
                    ]
                if skill.triggers:
                    patched.triggers = sorted(set(target.triggers) | set(skill.triggers))
                self.modules[skill.name] = patched
                continue

            if steps:
                # 여러 모듈을 순서대로 부르는 복합 스킬(결정 13: 순차 체이닝).
                self.modules[skill.name] = self._compose(skill)

        # 1단 모델도 다시 배운다. 스킬만 바뀌고 라우팅이 그대로면 배운 말이 사표가 된다.
        relearn = getattr(self.brain, "relearn", None)
        if relearn is not None:
            relearn(self.modules.values(), self.skills)

    def _compose(self, skill: Any) -> ModuleSpec:
        steps = list(skill.steps)

        def run(inst: Instruction) -> str:
            out = []
            for i, step in enumerate(steps, 1):
                mod = self.base_modules.get(step["module"])
                if mod is None:
                    # 없는 모듈을 부르는 스킬은 여기서 멈춘다. 조용히 건너뛰면
                    # 사용자는 절반만 수행된 걸 성공으로 오해한다.
                    raise ModuleFailed(f"step{i}:{step['module']}", "모듈 없음")
                sub = Instruction(text=inst.text, context={**inst.context, **step.get("params", {})})
                sub.tier = inst.tier
                out.append(mod.run(sub))
            return " / ".join(x for x in out if x)

        tiers: list[Tier] = []
        for step in steps:
            mod = self.base_modules.get(step["module"])
            if mod:
                tiers += mod.tiers
        ordered = [t for t in TIER_ORDER if t in tiers] or ["phone"]
        return ModuleSpec(
            name=skill.name,
            triggers=list(skill.triggers) or [skill.name],
            run=run,
            tiers=[skill.start_tier] if skill.start_tier else ordered,
        )

    # --- 로그 -----------------------------------------------------------

    def _emit(
        self,
        inst: Instruction,
        phase: str,
        outcome: str,
        *,
        step: str | None = None,
        latency_ms: int | None = None,
        failure_point: str | None = None,
        detail: dict[str, Any] | None = None,
    ) -> None:
        self.log(
            LogEvent(
                instruction_id=inst.id,
                seq=inst.next_seq(),
                phase=phase,  # type: ignore[arg-type]
                tier=inst.tier,
                outcome=outcome,  # type: ignore[arg-type]
                module=inst.module,
                step=step,
                latency_ms=latency_ms,
                retries=inst.retries,
                clarify_count=inst.clarify_count,
                failure_point=failure_point,
                detail=detail or {},
            )
        )

    # --- 모듈 선택 (결정 11) --------------------------------------------

    def select(self, inst: Instruction) -> ModuleSpec | list[str]:
        """규칙 → 소형 모델 → 되묻기. 확신 없이 실행하지 않는다."""
        hits = [m for m in self.modules.values() if m.matches(inst.text)]
        if len(hits) == 1:
            return hits[0]

        candidates = [m.name for m in (hits or self.modules.values())]
        if len(candidates) == 1:
            return self.modules[candidates[0]]

        if self.brain is not None:
            picked = self.brain.classify(inst.text, candidates)
            if picked in self.modules:
                return self.modules[picked]

        # 모호하다. 실행하지 않고 되묻는다 — 잘못 고르면 엉뚱한 모듈이 돌고 비용이 나간다.
        return candidates

    def _best_guess(self, candidates: list[str]) -> str | None:
        """되묻긴 하지만 1단 모델이 제일 가깝다고 본 것. 나중에 제안의 초안이 된다."""
        scores = getattr(self.brain, "last", None)
        if not scores:
            return None
        ranked = [(scores.get(c, 0.0), c) for c in candidates]
        top, name = max(ranked)
        return name if top > 0 else None

    # --- 실행 -----------------------------------------------------------

    def handle(self, text: str, context: dict[str, Any] | None = None) -> Reply:
        # context는 지시에 딸린 것들 — 사진, 위치 같은 것. 모듈이 꺼내 쓴다.
        inst = Instruction(text=text, context=context or {})
        self._emit(inst, "instruction_start", "success")

        t0 = time.perf_counter()
        chosen = self.select(inst)
        took = int((time.perf_counter() - t0) * 1000)

        if isinstance(chosen, list):
            inst.clarify_count += 1
            # 어떤 말에 막혔는지 남긴다. 후보 목록만으로는 나중에 "이 표현을 배워라"를
            # 만들 수 없다. 1단 모델의 1순위도 같이 남겨 승인 한 번으로 끝나게 한다.
            self._emit(inst, "module_select", "clarified", latency_ms=took,
                       detail={"candidates": chosen, "text": inst.text,
                               "best": self._best_guess(chosen)})
            names = " / ".join(chosen[:4])
            return Reply(f"어느 쪽이야? {names}", kind="clarify")

        inst.module = chosen.name
        self._emit(inst, "module_select", "success", latency_ms=took)

        reply = self._run_with_escalation(inst, chosen)

        if chosen.persistent and reply.kind == "result":
            # 지속형은 배경으로 내려가 계속 돈다(결정 21).
            self.background.append(inst)

        self._emit(inst, "done", "success" if reply.kind == "result" else "failure",
                   failure_point=None if reply.kind == "result" else inst.module,
                   latency_ms=int((time.perf_counter() - inst.started) * 1000))
        return reply

    def _run_with_escalation(self, inst: Instruction, mod: ModuleSpec) -> Reply:
        """모듈이 선언한 단계부터 시작해 실패하면 **한 번만** 위로 올린다(결정 24)."""
        tiers = [t for t in TIER_ORDER if t in mod.tiers] or ["phone"]
        start = TIER_ORDER.index(tiers[0])
        plan = TIER_ORDER[start : start + 2] if len(tiers) > 1 else tiers[:1]

        last: ModuleFailed | None = None
        for attempt, tier in enumerate(plan):
            inst.tier = tier
            inst.retries = attempt
            t0 = time.perf_counter()
            try:
                out = mod.run(inst)
            except ModuleFailed as e:
                last = e
                self._emit(inst, "module_run", "failure", step=e.where,
                           failure_point=e.where,
                           latency_ms=int((time.perf_counter() - t0) * 1000))
                continue
            self._emit(inst, "module_run", "success",
                       latency_ms=int((time.perf_counter() - t0) * 1000))
            return Reply(out, module=mod.name, render=mod.render)

        # 조용히 삼키지 않는다. 어디서 막혔는지 말한다(결정 24).
        where = last.where if last else "unknown"
        return Reply(
            f"{mod.name}을(를) 하려다 {where}에서 막혔어. 다음엔 되게 해볼게.",
            kind="failure",
            module=mod.name,
        )

    # --- 배경 (결정 21) --------------------------------------------------

    def ambient(self) -> list[Reply]:
        """배경 작업이 전경을 뚫고 올릴 알림. 뚫을 수 있다고 선언한 모듈만 낸다."""
        out = []
        for inst in self.background:
            mod = self.modules[inst.module or ""]
            if not mod.can_interrupt:
                continue
            try:
                text = mod.run(inst)
            except ModuleFailed as e:
                self._emit(inst, "module_run", "failure", step=e.where, failure_point=e.where)
                continue
            if text:
                out.append(Reply(text, kind="ambient", module=mod.name, render=mod.render))
        return out


def _self_check() -> None:
    events: list[LogEvent] = []

    def product_search(inst: Instruction) -> str:
        # 자택 서버에 비전 모델이 안 올라가 있는 상황. API로 승격되어야 한다.
        if inst.tier == "pc":
            raise ModuleFailed("vision_query", "로컬에 비전 모델 없음")
        return "필기구. 중고 시세 8천원"

    def volume_up(inst: Instruction) -> str:
        return "볼륨 올렸어"

    # 첫 호출은 안내 시작, 그다음은 알릴 게 없다가, 환승이 임박하면 뚫고 올라온다.
    nav_alerts = iter(["안내 시작", "", "곧 환승"])

    def navigate(inst: Instruction) -> str:
        return next(nav_alerts, "")

    mods = [
        ModuleSpec("product_search", ["이거 뭐야", "제품", "시세"], product_search,
                   tiers=["pc", "api"], needs=["camera"]),
        ModuleSpec("volume", ["볼륨"], volume_up),
        ModuleSpec("navigate", ["경로", "가는 길"], navigate,
                   persistent=True, can_interrupt=True, render="overlay"),
    ]

    class FakeBrain:
        picked: str | None = None

        def classify(self, text, choices):
            return self.picked

    brain = FakeBrain()
    eb = Orchestrator(mods, brain, events.append)

    # 규칙 매칭 한 방 — 소형 모델을 안 부른다.
    r = eb.handle("볼륨 올려줘")
    assert r.kind == "result" and r.text == "볼륨 올렸어"
    assert [e.phase for e in events] == ["instruction_start", "module_select", "module_run", "done"]
    assert all(e.tier == "phone" for e in events)

    # 폰에서 실패 → 상위로 1회 승격 → 성공 (결정 24)
    events.clear()
    r = eb.handle("이거 뭐야")
    assert r.kind == "result" and "시세" in r.text
    tiers = [e.tier for e in events if e.phase == "module_run"]
    assert tiers == ["pc", "api"], f"승격 경로가 다르다: {tiers}"
    fail = [e for e in events if e.outcome == "failure"][0]
    assert fail.failure_point == "vision_query", "실패 지점이 안 남았다"
    assert fail.retries == 0 and events[-1].latency_ms is not None

    # 모호하면 실행하지 않고 되묻는다 (결정 11)
    events.clear()
    brain.picked = None
    r = eb.handle("그거 좀 해줘")
    assert r.kind == "clarify", "모호한데 실행해버렸다"
    assert not [e for e in events if e.phase == "module_run"], "되묻기인데 모듈이 돌았다"
    assert [e for e in events if e.outcome == "clarified"][0].detail["candidates"]

    # 소형 모델이 고르면 그대로 간다.
    brain.picked = "volume"
    assert eb.handle("그거 좀 해줘").text == "볼륨 올렸어"

    # 지속형은 배경으로 내려가고, 뚫을 수 있다고 선언한 것만 알린다 (결정 21)
    brain.picked = None
    assert eb.handle("경로 안내 시작해").kind == "result"
    assert len(eb.background) == 1
    assert eb.ambient() == [], "빈 알림이 올라왔다"
    alerts = eb.ambient()
    assert len(alerts) == 1 and alerts[0].kind == "ambient" and alerts[0].render == "overlay"

    # 전 단계에서 실패하면 어디서 막혔는지 말한다 (결정 24)
    events.clear()
    always_fail = ModuleSpec(
        "translate", ["통역"], lambda i: (_ for _ in ()).throw(ModuleFailed("stt")),
        tiers=["pc", "api"],
    )
    eb2 = Orchestrator([always_fail], None, events.append)
    r = eb2.handle("통역 시작")
    assert r.kind == "failure" and "stt" in r.text
    assert len([e for e in events if e.outcome == "failure"]) == 3  # 시도 2 + done

    # --- 학습 결과가 실제 동작을 바꾸는가 (결정 17의 마지막 고리) ---
    from skills import Skill

    events.clear()
    eb3 = Orchestrator(mods, None, events.append)

    # 승인 전: 자택 서버에서 한 번 헛걸음하고 API로 올라간다.
    eb3.handle("이거 뭐야")
    before = [e.tier for e in events if e.phase == "module_run"]
    assert before == ["pc", "api"], before

    # 낭비 감지가 만든 스킬을 적용한다.
    events.clear()
    eb3.load_skills([Skill(name="product_search", start_tier="api")])
    eb3.handle("이거 뭐야")
    after = [e.tier for e in events if e.phase == "module_run"]
    assert after == ["api"], f"스킬이 동작을 안 바꿨다: {after}"

    # 스킬을 빼면 원래대로 돌아온다 — 되돌리기가 다시 부르는 것으로 끝난다.
    events.clear()
    eb3.load_skills([])
    eb3.handle("이거 뭐야")
    assert [e.tier for e in events if e.phase == "module_run"] == ["pc", "api"]

    # 트리거 추가: 되묻던 표현이 한 번에 잡힌다.
    eb3.load_skills([Skill(name="volume", triggers=["그거 좀 해줘"])])
    assert eb3.handle("그거 좀 해줘").text == "볼륨 올렸어"

    # 복합 스킬: 여러 모듈을 순서대로 부른다 (결정 13 순차 체이닝)
    eb3.load_skills([
        Skill(name="출근 준비", triggers=["출근 준비"],
              steps=[{"module": "volume"}, {"module": "navigate"}]),
    ])
    combo = eb3.handle("출근 준비")
    assert combo.kind == "result" and "볼륨 올렸어" in combo.text

    # 없는 모듈을 부르는 스킬은 절반만 하고 성공했다고 하지 않는다.
    eb3.load_skills([
        Skill(name="깨진 스킬", triggers=["깨진"],
              steps=[{"module": "volume"}, {"module": "없는모듈"}]),
    ])
    broken = eb3.handle("깨진 것 실행")
    assert broken.kind == "failure" and "없는모듈" in broken.text, broken

    print("orchestrator self-check 통과")


if __name__ == "__main__":
    _self_check()
