"""선언적 스킬과 분석기 (결정 17·18).

스킬은 **코드가 아니라 데이터**다. 어떤 지시에 반응해 어떤 모듈을 어떤 순서·파라미터로
부를지 적은 선언문이고, 실행은 기존 모듈 조합으로만 이뤄진다. 그래서 사람이 읽을 수 있고,
틀리면 지울 수 있고, 실행 전에 검증할 수 있다 — 생성된 코드는 셋 다 안 된다.

스킬은 마크다운 항목으로 저장된다(결정 30). 선언문은 프론트매터에 들어가므로
옵시디언에서 열어 직접 고칠 수 있다.

분석기는 지금 **규칙 기반**이다. 큰 모델에게 이력을 통째로 주는 방식은 데이터가 쌓인 뒤에
얹는다 — 지금은 제안할 이력 자체가 없고, 규칙만으로도 명백한 낭비는 잡힌다.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any

from notes import Note, Notes

MIN_EVIDENCE = 3  # 이만큼 반복돼야 제안한다. 한두 번은 우연이다.


@dataclass
class Skill:
    """선언문. 실행기는 이 데이터만 보고 모듈을 부른다."""

    name: str
    triggers: list[str] = field(default_factory=list)
    # 1단 모델이 배우는 말들(결정 11). 트리거는 글자 그대로 맞아야 하지만 예시는
    # 비슷하기만 하면 된다 — 되묻던 표현이 승인되면 여기 쌓여 다음부터 안 되묻는다.
    examples: list[str] = field(default_factory=list)
    steps: list[dict[str, Any]] = field(default_factory=list)
    start_tier: str | None = None  # 정해두면 이 단계부터 시작한다(결정 5 매핑 조정)
    version: int = 1
    previous: dict[str, Any] | None = None  # 되돌리기용 직전 버전(결정 18)

    def to_note(self) -> Note:
        body = [
            f"스킬 **{self.name}** (v{self.version}).",
            "",
            f"- 반응: {', '.join(self.triggers) or '없음'}",
        ]
        if self.examples:
            body.append(f"- 배운 말: {', '.join(self.examples)}")
        for i, s in enumerate(self.steps, 1):
            body.append(f"- {i}단계: [[{s['module']}]] {json.dumps(s.get('params', {}), ensure_ascii=False)}")
        if self.start_tier:
            body.append(f"- 시작 단계: {self.start_tier}")
        return Note(
            title=self.name,
            body="\n".join(body),
            kind="skill",
            declaration=asdict(self),
        )

    @classmethod
    def from_note(cls, note: Note) -> Skill | None:
        d = note.declaration
        if not d:
            return None
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


class SkillStore:
    def __init__(self, notes: Notes) -> None:
        self.notes = notes

    def save(self, skill: Skill) -> Skill:
        # 읽고-합치고-쓰기라 잠근다 — 동시에 배우면 한쪽이 배운 말이 사라진다.
        with self.notes._글잠금(skill.name):
            return self._save(skill)

    def _save(self, skill: Skill) -> Skill:
        """새 버전을 저장하면서 직전 버전을 안에 남긴다. 되돌릴 곳이 있어야 한다(결정 18).

        ponytail: 한 단계만 되돌아간다. 전체 이력이 필요해지면 그때 버전별 항목으로 나눈다.
        """
        old = self.load(skill.name)
        if old:
            skill.version = old.version + 1
            # 배운 말은 덮지 않고 쌓는다. 새 표현 하나 배웠다고 전에 배운 걸 잃으면
            # 같은 말을 또 되묻게 된다.
            skill.examples = list(dict.fromkeys([*old.examples, *skill.examples]))
            skill.triggers = list(dict.fromkeys([*old.triggers, *skill.triggers]))
            skill.start_tier = skill.start_tier or old.start_tier
            skill.steps = skill.steps or old.steps
            skill.previous = asdict(old)
            skill.previous.pop("previous", None)  # 이력이 무한히 중첩되지 않게
        self.notes.write(skill.to_note())
        return skill

    def load(self, name: str) -> Skill | None:
        note = self.notes.read(name)
        return Skill.from_note(note) if note else None

    def revert(self, name: str) -> Skill | None:
        with self.notes._글잠금(name):
            return self._revert(name)

    def _revert(self, name: str) -> Skill | None:
        cur = self.load(name)
        if not cur or not cur.previous:
            return None
        prev = Skill(**cur.previous)
        prev.version = cur.version + 1  # 되돌린 것도 하나의 변경이다
        prev.previous = asdict(cur)
        prev.previous.pop("previous", None)
        self.notes.write(prev.to_note())
        return prev

    def all(self) -> list[Skill]:
        out = []
        for row in self.notes.conn.execute("SELECT title FROM notes WHERE kind = 'skill'"):
            s = self.load(row["title"])
            if s:
                out.append(s)
        return out


# --- 분석기 -------------------------------------------------------------


def _proposal(kind: str, title: str, summary: str, based_on: list[str], decl: dict) -> dict:
    return {
        "proposal_id": uuid.uuid4().hex[:16],
        "type": kind,
        "title": title,
        "summary": summary,
        "based_on": based_on,
        "declaration": decl,
    }


def find_tier_waste(conn: sqlite3.Connection) -> list[dict]:
    """낮은 단계에서 늘 실패하고 위에서 성공하는 모듈을 찾는다.

    성공한 지시도 분석 대상이다(오너 지시) — 결과가 맞았어도 **가는 길에 낭비가 있었다.**
    매번 실패할 걸 알면서 폰에서 한 번 시도하는 것은 지연과 배터리를 그냥 버리는 것이다.
    """
    rows = conn.execute(
        """
        SELECT module, tier, failure_point, COUNT(*) AS n
        FROM log_events
        WHERE phase = 'module_run' AND outcome = 'failure' AND module IS NOT NULL
        GROUP BY module, tier, failure_point
        HAVING n >= ?
        """,
        (MIN_EVIDENCE,),
    ).fetchall()

    out = []
    for r in rows:
        succeeded = conn.execute(
            "SELECT COUNT(*) FROM log_events WHERE module = ? AND phase = 'module_run' "
            "AND outcome = 'success' AND tier != ?",
            (r["module"], r["tier"]),
        ).fetchone()[0]
        if succeeded < MIN_EVIDENCE:
            continue  # 위에서도 안 되는 거면 단계 문제가 아니다
        evidence = [
            e["instruction_id"]
            for e in conn.execute(
                "SELECT DISTINCT instruction_id FROM log_events "
                "WHERE module = ? AND outcome = 'failure' AND tier = ? LIMIT 5",
                (r["module"], r["tier"]),
            )
        ]
        higher = "pc" if r["tier"] == "phone" else "api"
        out.append(
            _proposal(
                "skill_update",
                f"{r['module']}는 {higher}부터 시작",
                f"{r['tier']} 단계에서 {r['failure_point']}로 {r['n']}번 실패했고 "
                f"위 단계에서는 {succeeded}번 성공했어. 처음부터 {higher}로 보내면 "
                f"매번 한 번씩 헛걸음하는 걸 없앨 수 있어.",
                evidence,
                asdict(Skill(name=r["module"], start_tier=higher)),
            )
        )
    return out


def find_clarify_pattern(conn: sqlite3.Connection) -> list[dict]:
    """되묻기가 반복되는 표현을 찾는다. 같은 말을 매번 못 알아듣는 건 트리거가 없다는 뜻이다."""
    rows = conn.execute(
        """
        SELECT detail, COUNT(*) AS n
        FROM log_events
        WHERE phase = 'module_select' AND outcome = 'clarified'
        GROUP BY detail
        HAVING n >= ?
        """,
        (MIN_EVIDENCE,),
    ).fetchall()

    out = []
    for r in rows:
        detail = json.loads(r["detail"])
        candidates = detail.get("candidates") or []
        if len(candidates) < 2:
            continue
        evidence = [
            e["instruction_id"]
            for e in conn.execute(
                "SELECT DISTINCT instruction_id FROM log_events "
                "WHERE outcome = 'clarified' AND detail = ? LIMIT 5",
                (r["detail"],),
            )
        ]
        phrase = (detail.get("text") or "").strip()
        best = detail.get("best")

        # 1단 모델이 짚은 게 있으면 그걸 초안으로 낸다 — 승인 한 번이면 끝난다.
        # 없으면 어느 쪽인지 물어야 하므로 배울 말을 넣지 않는다(결정 18: 확신 없이 굳히지 않는다).
        if phrase and best in candidates:
            summary = (
                f"'{phrase}'를 {r['n']}번 되물었어. {best} 얘기 같은데, "
                f"맞으면 승인해줘. 다음부터 안 물어볼게."
            )
            declaration = {"name": best, "examples": [phrase]}
        elif phrase:
            # 1단 모델도 짚지 못했다. 찍지 않고 고르게 한다(결정 18).
            summary = (
                f"'{phrase}'를 {r['n']}번 되물었어. 어느 쪽인지 한 번만 골라주면 "
                f"그 말을 배워서 다음부터 안 물어볼게."
            )
            declaration = {"candidates": candidates, "examples": [phrase]}
        else:
            summary = (
                f"{', '.join(candidates[:4])} 사이에서 {r['n']}번 되물었어. "
                f"어느 쪽을 뜻하는지 한 번만 정해주면 다음부터 안 물어볼게."
            )
            declaration = {"candidates": candidates}

        out.append(
            _proposal("intervention_proposal", "매번 되묻는 표현이 있어",
                      summary, evidence, declaration)
        )
    return out


def analyze(conn: sqlite3.Connection) -> list[dict]:
    """지금은 규칙 둘. 큰 모델을 붙이는 자리가 여기다 — 이력이 쌓인 뒤에 얹는다."""
    return find_tier_waste(conn) + find_clarify_pattern(conn)


def _self_check() -> None:
    import tempfile
    from pathlib import Path

    from store import Store

    with tempfile.TemporaryDirectory() as tmp:
        notes = Notes(Path(tmp) / "notes")
        skills = SkillStore(notes)

        s = skills.save(Skill(name="출근 준비", triggers=["출근 준비"],
                              steps=[{"module": "navigate", "params": {"to": "회사"}}]))
        assert s.version == 1 and s.previous is None

        # ★★ **스킬은 코드가 아니라 데이터다 — 나쁜 선언문이 와도 안 깨져야 한다.**
        #   밖에서 손으로 고칠 수 있는 자리라(옵시디언에서 연다) 뭐든 들어온다.
        #   재 보니 여섯 가지가 다 조용히 걸러지고 멀쩡한 것만 읽힌다. 그걸 못 박는다.
        험한것 = {
            "앞머리가 깨진 스킬": '---' + chr(10) + 'kind: "skill"' + chr(10)
                              + 'steps: [안 닫힘' + chr(10) + '---' + chr(10) + '몸',
            "steps 가 글자": '---' + chr(10) + 'kind: "skill"' + chr(10)
                          + 'steps: "이건 목록이 아니다"' + chr(10) + '---' + chr(10) + '몸',
            "steps 가 숫자": '---' + chr(10) + 'kind: "skill"' + chr(10)
                          + 'steps: 42' + chr(10) + '---' + chr(10) + '몸',
            "아주 깊은 스킬": '---' + chr(10) + 'kind: "skill"' + chr(10)
                          + 'steps: ' + "[" * 200 + "]" * 200 + chr(10) + '---' + chr(10) + '몸',
            "이상한 모듈": '---' + chr(10) + 'kind: "skill"' + chr(10)
                        + 'steps: [{"module": "../../etc/passwd"}]' + chr(10) + '---' + chr(10) + '몸',
        }
        for 이름, 글 in 험한것.items():
            (notes.root / f"{이름}.md").write_text(글, encoding="utf-8")
        notes.reindex()
        읽힌것 = skills.all()
        assert [x.name for x in 읽힌것] == ["출근 준비"],             f"나쁜 선언문이 스킬로 읽힌다: {[x.name for x in 읽힌것]}"
        for 이름 in 험한것:
            (notes.root / f"{이름}.md").unlink()
        notes.reindex()

        s2 = skills.save(Skill(name="출근 준비", triggers=["출근 준비", "나갈 준비"],
                               steps=[{"module": "navigate", "params": {"to": "회사"}}]))
        assert s2.version == 2 and s2.previous["triggers"] == ["출근 준비"]

        back = skills.revert("출근 준비")
        assert back is not None and back.triggers == ["출근 준비"], "되돌리기가 안 된다"
        assert back.version == 3, "되돌린 것도 변경으로 센다"
        assert skills.revert("없는 스킬") is None

        # 옵시디언에서 열어 고칠 수 있어야 한다 — 선언문이 파일에 남아 있는지 본다.
        raw = notes.path_of("출근 준비").read_text(encoding="utf-8")
        assert "declaration:" in raw and "navigate" in raw
        assert len(skills.all()) == 1

        # --- 분석기 ---
        st = Store(":memory:")

        def log(iid, seq, phase, tier, outcome, **kw):
            st.add_log(dict(
                instruction_id=iid, seq=seq, ts="2026-08-05T00:00:00Z", phase=phase,
                tier=tier, outcome=outcome, module=kw.get("module"), step=None,
                latency_ms=10, tokens_in=None, tokens_out=None, cost_krw=0.0,
                retries=0, clarify_count=0, failure_point=kw.get("failure_point"),
                detail=kw.get("detail", {}),
            ))

        assert analyze(st.conn) == [], "증거가 없는데 제안이 나왔다"

        # 폰에서 3번 실패하고 PC에서 3번 성공 → 낭비다
        for i in range(3):
            log(f"i{i}", 1, "module_run", "phone", "failure",
                module="product_search", failure_point="vision_model")
            log(f"i{i}", 2, "module_run", "pc", "success", module="product_search")

        props = analyze(st.conn)
        assert len(props) == 1, f"낭비 제안이 안 나왔다: {props}"
        p = props[0]
        assert p["type"] == "skill_update"
        assert p["declaration"]["start_tier"] == "pc"
        assert len(p["based_on"]) == 3, "근거 지시가 안 붙었다"

        # 위 단계에서도 안 되면 단계 문제가 아니므로 제안하지 않는다
        st2 = Store(":memory:")
        for i in range(3):
            st2.add_log(dict(
                instruction_id=f"j{i}", seq=1, ts="2026-08-05T00:00:00Z", phase="module_run",
                tier="phone", outcome="failure", module="translate", step=None,
                latency_ms=1, tokens_in=None, tokens_out=None, cost_krw=0.0, retries=0,
                clarify_count=0, failure_point="stt", detail={},
            ))
        assert analyze(st2.conn) == [], "위에서도 실패하는데 승격을 제안했다"

        # 같은 후보들로 3번 되물으면 정해달라고 제안한다
        for i in range(3):
            log(f"c{i}", 1, "module_select", "phone", "clarified",
                detail={"candidates": ["volume", "navigate"]})
        clarify = [p for p in analyze(st.conn) if p["type"] == "intervention_proposal"]
        assert len(clarify) == 1 and clarify[0]["declaration"]["candidates"] == ["volume", "navigate"]

        # 어떤 말에 막혔는지 남아 있으면, 배울 말을 넣은 초안으로 낸다.
        for i in range(3):
            log(f"d{i}", 1, "module_select", "phone", "clarified",
                detail={"candidates": ["volume", "navigate"],
                        "text": "그거 좀 해줘", "best": "volume"})
        drafted = [p for p in analyze(st.conn)
                   if p["type"] == "intervention_proposal" and "examples" in p["declaration"]]
        assert len(drafted) == 1, drafted
        assert drafted[0]["declaration"] == {"name": "volume", "examples": ["그거 좀 해줘"]}
        assert "그거 좀 해줘" in drafted[0]["summary"]

        # 승인하면 배운 말이 스킬에 쌓인다. 다음에 또 배워도 앞의 것을 안 잃는다.
        store = SkillStore(notes)
        store.save(Skill(name="volume", examples=["그거 좀 해줘"]))
        store.save(Skill(name="volume", examples=["그거 해봐"]))
        grown = store.load("volume")
        assert grown.examples == ["그거 좀 해줘", "그거 해봐"], grown.examples
        assert grown.version == 2

    print("skills self-check 통과")


if __name__ == "__main__":
    _self_check()
