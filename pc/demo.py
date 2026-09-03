"""키보드로 VC를 불러보는 데모 (결정 26).

폰이 하는 일을 키보드가 대신한다. 오케스트레이터가 실제로 도는 것을 지금 볼 수 있고,
폰이 오면 입력을 음성으로, 출력을 HUD로 갈아 끼운다.

    python -X utf8 server.py        # 다른 창에서 먼저 띄운다
    python -X utf8 demo.py

서버가 안 떠 있어도 동작한다 — 로그를 버퍼에 쌓아 두었다가 다음 연결 때 보낸다(결정 17).
PC가 꺼져도 VC는 죽지 않는다(결정 25).
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import asdict

import brain
import talklog
from eb_protocol import LogEvent
from orchestrator import Instruction, ModuleFailed, ModuleSpec, Orchestrator
from modules import build_modules
from server import load_config
from skills import Skill


class PhoneLink:
    """폰이 PC에 로그를 흘려보내는 쪽. 실패하면 버퍼에 쌓는다.

    PC가 꺼져 있을 때 매 이벤트마다 다시 두들기면 지시가 눈에 띄게 느려지고,
    폰에서는 그게 그대로 배터리다. 한 번 실패하면 잠깐 쉬었다가 다시 본다.
    """

    RETRY_AFTER_SEC = 30
    MAX_BUFFER = 5000  # ponytail: 넘치면 오래된 것부터 버린다. 디스크 버퍼는 필요해지면.

    def __init__(self, base: str, token: str) -> None:
        self.base = base.rstrip("/")
        self.token = token
        self.buffer: list[LogEvent] = []
        self.retry_at = 0.0

    def send(self, event: LogEvent) -> None:
        self.buffer.append(event)
        del self.buffer[: max(0, len(self.buffer) - self.MAX_BUFFER)]

        if time.monotonic() < self.retry_at:
            return

        pending, self.buffer = self.buffer, []
        for i, e in enumerate(pending):
            if not self._post(e):
                # 한 건이 실패하면 링크가 죽은 것이다. 나머지는 시도하지 않는다.
                self.buffer = pending[i:]
                self.retry_at = time.monotonic() + self.RETRY_AFTER_SEC
                return

    def _post(self, event: LogEvent) -> bool:
        req = urllib.request.Request(
            f"{self.base}/eb/v1/log",
            data=json.dumps(asdict(event), ensure_ascii=False).encode(),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.token}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=2):
                return True
        except (urllib.error.URLError, OSError):
            return False

    def call(self, method: str, path: str, payload: dict | None = None) -> dict | None:
        """PC에 묻는다. PC가 없으면 None — VC는 그래도 동작한다(결정 25)."""
        req = urllib.request.Request(
            f"{self.base}{path}",
            data=None if payload is None else json.dumps(payload, ensure_ascii=False).encode(),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.token}",
            },
            method=method,
        )
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                raw = r.read().decode()
                return json.loads(raw) if raw else {}
        except (urllib.error.URLError, OSError):
            return None


HELP = """지시를 그냥 쓰면 된다. 앞에 붙는 명령:
  :분석    PC에게 이력을 돌아보게 한다
  :제안    대기 중인 제안 목록
  :승인 N  N번 제안을 승인하고 스킬로 반영
  :스킬    지금 적용된 스킬
  :판정 말  1단 모델이 그 말을 어떻게 보는지 점수로 보여준다
  :엔진    지금 올라온 모델과 가진 모델 목록
  :음성    말로 부르기 (호출어 "브이씨" 또는 "불칸"). Ctrl+C로 빠져나온다
  :기록    최근 대화 기록
  빈 줄    종료"""


def voice_loop(eb: Orchestrator, say) -> None:
    """말로 부르는 고리. VC를 부르고 지시를 말하면 듣고 답한다.

    이름은 둘 다 받는다 — "브이씨"(제품)와 "불칸"(만든 곳).

    호출어만 부르면 실행하지 않고 기다린다 — 두 이름 모두 짧아서 오인식이 잦고,
    잘못 깨어나 엉뚱한 걸 실행하면 되돌리는 쪽이 더 비싸다(결정 11).
    """
    import voice

    ears, mouth = voice.Ears(), voice.Mouth()
    talk = voice.Talk()
    vocab = [*eb.modules] + [t for m in eb.modules.values() for t in m.triggers]
    names = " / ".join(f'"{w}"' for w in voice.WAKE_WORDS)
    print(f'  듣는 중. {names} 중 아무거나 불러봐. (Ctrl+C로 나감)')

    pending = False  # 호출어만 듣고 지시를 기다리는 중
    while True:
        heard = ears.listen(mouth)
        if not heard:
            continue
        print(f"  들음: {heard}")

        if pending:
            order, pending = heard, False  # 방금 불렀으니 이번 말이 지시다
        else:
            woke, order = talk.take(heard)
            if not woke:
                continue
            if not order:
                pending = True
                mouth.say("응")
                continue

        t0 = time.monotonic()
        reply = eb.handle(order)
        talk.opened()
        print(f"  VC: {reply.text}")
        talklog.record(heard=heard, woke=True, order=order, reply=reply.text,
                       kind=reply.kind, took={"처리": round(time.monotonic() - t0, 2)},
                       stt=f"{ears.device}/{ears.model_size}")
        mouth.say(reply.text)


def sync_skills(eb: Orchestrator, link: PhoneLink) -> int:
    """승인된 스킬을 받아 오케스트레이터에 반영한다(결정 17의 마지막 고리)."""
    got = link.call("GET", "/eb/v1/skills")
    if got is None:
        return 0
    loaded = [Skill(**{k: v for k, v in s.items() if k in Skill.__dataclass_fields__})
              for s in got["skills"]]
    eb.load_skills(loaded)
    return len(loaded)


def main() -> None:
    cfg = load_config()
    link = PhoneLink("http://127.0.0.1:8765", cfg["pair_token"])
    modules = build_modules()
    # 1단 온디바이스 모델. 규칙으로 안 갈리는 말을 여기서 고르고, 그래도 모르면 되묻는다.
    eb = Orchestrator(modules, brain=brain.build(modules), log=link.send)
    sync_skills(eb, link)

    print("VC 데모.")
    print(HELP)
    pending: list[dict] = []

    while True:
        try:
            text = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not text:
            break

        if text.startswith(":"):
            cmd, _, arg = text[1:].partition(" ")

            if cmd == "분석":
                out = link.call("POST", "/eb/v1/analyze", {})
                print("  PC 미연결" if out is None else f"  새 제안 {len(out['created'])}건 / 찾음 {out['found']}건")

            elif cmd == "제안":
                out = link.call("GET", "/eb/v1/proposals")
                if out is None:
                    print("  PC 미연결")
                else:
                    pending = out["proposals"]
                    for i, p in enumerate(pending):
                        print(f"  [{i}] {p['title']}\n      {p['summary']}")
                    if not pending:
                        print("  대기 중인 제안 없음")

            elif cmd == "승인":
                # ":승인 0" 은 그대로 승인, ":승인 0 번역" 은 후보 중 번역을 고른다.
                num, _, pick = arg.partition(" ")
                if not num.isdigit() or int(num) >= len(pending):
                    print("  :제안 으로 번호를 먼저 확인해")
                else:
                    p = pending[int(num)]
                    decision = f"pick:{pick.strip()}" if pick.strip() else "approve"
                    out = link.call("POST", f"/eb/v1/proposals/{p['proposal_id']}/decision",
                                    {"decision": decision})
                    print("  PC 미연결" if out is None else f"  반영됨 — 스킬 {sync_skills(eb, link)}개")

            elif cmd == "판정":
                if not arg:
                    print("  :판정 뒤에 말을 붙여")
                else:
                    scores = eb.brain.score(arg, list(eb.modules))
                    for name, s in sorted(scores.items(), key=lambda kv: -kv[1])[:4]:
                        print(f"  {s:.2f}  {name}")
                    picked = eb.brain.classify(arg, list(eb.modules))
                    print(f"  → {picked or '확신 없음 (되묻는다)'}")

            elif cmd == "음성":
                try:
                    voice_loop(eb, print)
                except KeyboardInterrupt:
                    print("\n  키보드로 돌아옴")
                except Exception as e:
                    # 마이크·모델 문제로 VC가 통째로 죽으면 안 된다. 키보드로 계속 쓴다.
                    print(f"  음성을 못 켰어: {e}")

            elif cmd == "기록":
                print(talklog.show(int(arg) if arg.isdigit() else 20))

            elif cmd == "엔진":
                out = link.call("GET", "/eb/v1/engine")
                if out is None:
                    print("  PC 미연결")
                else:
                    print(f"  종류 {out['kind']} / 올라옴: {out['loaded'] or '없음'}")
                    for m in out["models"]:
                        print(f"    - {m}")

            elif cmd == "스킬":
                for name, mod in eb.modules.items():
                    if name not in eb.base_modules or mod is not eb.base_modules[name]:
                        print(f"  {name}: 시작 {mod.tiers[0]}, 반응 {mod.triggers}")

            else:
                print(HELP)
            continue

        reply = eb.handle(text)
        mark = {"result": "VC", "clarify": "VC?", "failure": "VC!"}.get(reply.kind, "VC")
        print(f"{mark}: {reply.text}")

        for alert in eb.ambient():
            print(f"  (배경) {alert.text}")

        if link.buffer:
            print(f"  [로그 {len(link.buffer)}건 대기 — PC 미연결]")


if __name__ == "__main__":
    main()
