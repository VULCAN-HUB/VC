"""기기끼리 **바뀐 것을 서로 알려 주는 그물** (오너 2026-09-24).

오너가 정한 것:
  · 감시(훑기)로 알아내지 말고, **저장·추가·지움을 누른 그 순간 신호를 쏜다.**
  · 메인이든 손님이든 **어느 기계에서나** 된다 — 한 대가 중심이 아니다.
  · 「서로서로, PC 에 별다른 설정 없이 — VC 깔고 테일스케일과 VC 설정만」.

그래서 **주소를 사람이 적지 않는다.** 테일스케일에게 이웃 목록을 물어보고,
켜져 있는 이웃마다 `/eb/v1/events` 에 귀를 붙인다. 기계가 늘어도 할 일이 없다.

★★ **신호는 「바뀌었다」만 나른다 — 글 몸은 안 싣는다.** 받은 쪽이 제 창고를
   다시 본다. 몸을 실으면 누가 이겼는지 두 군데서 정하게 되고, 창고가 NAS 에
   하나뿐인 지금은 다시 보기만 하면 된다.
★★ **못 닿는 이웃은 조용히 넘긴다.** 꺼져 있는 기계 하나 때문에 나머지가 멈추면
   안 된다 — 끊기면 쉬었다 다시 건다.
★ 이웃 **이름은 쓰지도 적지도 않는다.** 컴퓨터 이름에 사람 이름이 들어 있다
  (전역 규칙). 주소만 본다.
"""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
from typing import Callable, Iterable

import tailnet

기본포트 = 8765
쉬는초 = 5.0             # 끊긴 이웃에 다시 걸기까지
찾기주기초 = 60.0        # 이웃 목록을 다시 물어보기까지
붙는제한초 = 6.0         # 이웃에 귀를 붙일 때 기다리는 한도


def 이웃주소들(status_json: str | None = None) -> list[str]:
    """지금 **켜져 있는** 테일스케일 이웃의 주소. 사람이 적을 것이 없다.

    ★ 이름은 안 본다 — 주소만. 컴퓨터 이름에 사람 이름이 들어 있다.
    """
    글 = status_json
    if 글 is None:
        for 명령 in tailnet._명령들():
            글 = tailnet._run([명령, "status", "--json"])
            if 글:
                break
    if not 글:
        return []
    try:
        d = json.loads(글)
    except ValueError:
        return []
    난것: list[str] = []
    for 동무 in (d.get("Peer") or {}).values():
        if not isinstance(동무, dict) or not 동무.get("Online"):
            continue
        for 주소 in 동무.get("TailscaleIPs") or []:
            if isinstance(주소, str) and 주소.count(".") == 3:   # IPv4 만
                난것.append(주소)
                break
    return 난것


def 나인가(주소: str, 내주소: str | None = None) -> bool:
    """나 자신이면 귀를 안 붙인다 — 제 신호를 되받으면 끝없이 돈다."""
    내주소 = 내주소 if 내주소 is not None else (tailnet.tailscale_ip() or "")
    return bool(내주소) and 주소 == 내주소


class 그물:
    """이웃을 찾아 붙고, 신호가 오면 알려 준다.

    ★★ **한 이웃에 귀 하나.** 같은 이웃에 둘 붙으면 같은 신호를 두 번 받아
       창고를 두 번 다시 본다 — 값만 든다.
    """

    def __init__(self, 열쇠: str, 받으면: Callable[[dict], None],
                 포트: int = 기본포트, 여는이: Callable | None = None) -> None:
        self.열쇠 = 열쇠 or ""
        self.받으면 = 받으면
        self.포트 = 포트
        self._여는이 = 여는이 or self._열기
        self._붙은것: dict[str, threading.Thread] = {}
        self._그만 = threading.Event()
        self._잠금 = threading.Lock()
        self.받은수 = 0

    # --- 이웃에 귀 붙이기 ---------------------------------------------
    def _열기(self, 주소: str):
        요청 = urllib.request.Request(
            f"http://{주소}:{self.포트}/eb/v1/events",
            headers={"Authorization": f"Bearer {self.열쇠}",
                     "Accept": "text/event-stream"})
        return urllib.request.urlopen(요청, timeout=붙는제한초)

    def _한이웃(self, 주소: str) -> None:
        while not self._그만.is_set():
            try:
                응답 = self._여는이(주소)
            except (urllib.error.URLError, OSError, ValueError):
                # 꺼져 있거나 열쇠가 안 맞는다. **조용히 쉬었다 다시** — 하나 때문에
                # 나머지가 멈추면 안 된다.
                if self._그만.wait(쉬는초):
                    return
                continue
            try:
                for 줄 in 응답:
                    if self._그만.is_set():
                        return
                    줄 = 줄.decode("utf-8", "replace").strip()
                    if not 줄.startswith("data:"):
                        continue          # keepalive 따위
                    try:
                        것 = json.loads(줄[5:].strip())
                    except ValueError:
                        continue
                    self.받은수 += 1
                    try:
                        self.받으면(것)
                    except Exception:
                        pass              # 받아서 하는 일이 터져도 귀는 붙어 있는다
            except (OSError, ValueError):
                pass
            finally:
                try:
                    응답.close()
                except Exception:
                    pass
            if self._그만.wait(쉬는초):
                return

    def 맞추기(self, 주소들: Iterable[str]) -> int:
        """이웃 목록에 맞춰 귀를 붙인다. 새로 붙은 수를 돌려준다."""
        새로 = 0
        with self._잠금:
            for 주소 in 주소들:
                if 주소 in self._붙은것 or 나인가(주소):
                    continue
                실 = threading.Thread(target=self._한이웃, args=(주소,),
                                    name="그물귀", daemon=True)
                self._붙은것[주소] = 실
                실.start()
                새로 += 1
        return 새로

    def 돌기(self, 주기초: float = 찾기주기초) -> None:
        """이웃을 틈틈이 다시 찾는다. 기계가 늘어도 사람이 할 일이 없다."""
        def 돌이() -> None:
            while not self._그만.is_set():
                try:
                    self.맞추기(이웃주소들())
                except Exception:
                    pass          # 못 찾아도 다음 바퀴에 다시
                if self._그만.wait(주기초):
                    return

        threading.Thread(target=돌이, name="그물찾기", daemon=True).start()

    def 그만두기(self) -> None:
        self._그만.set()

    @property
    def 붙은수(self) -> int:
        return len(self._붙은것)


def _self_check() -> None:
    import io

    # --- 이웃 찾기: 이름은 안 보고 주소만, 꺼진 것은 뺀다 ---
    본보기 = json.dumps({
        "Self": {"TailscaleIPs": ["100.1.1.1"]},
        "Peer": {
            "a": {"Online": True, "TailscaleIPs": ["100.2.2.2", "fd7a::1"],
                  "HostName": "사람이름-맥"},
            "b": {"Online": False, "TailscaleIPs": ["100.3.3.3"]},
            "c": {"Online": True, "TailscaleIPs": []},
        }})
    assert 이웃주소들(본보기) == ["100.2.2.2"], 이웃주소들(본보기)
    assert 이웃주소들("") == [] and 이웃주소들("{깨진") == []
    # ★ IPv6 는 안 쓴다 — 문이 IPv4 로 열려 있다
    assert all(a.count(".") == 3 for a in 이웃주소들(본보기))

    # ★★ **나 자신에게는 안 붙는다** — 제 신호를 되받으면 끝없이 돈다
    assert 나인가("100.1.1.1", "100.1.1.1") and not 나인가("100.2.2.2", "100.1.1.1")
    assert not 나인가("100.1.1.1", "")       # 내 주소를 모르면 막지 않는다

    # --- 신호 받기: 가짜 이웃을 열어 끝까지 태운다 ---
    받은: list[dict] = []
    열린수 = {"n": 0}

    def 가짜열기(주소: str):
        열린수["n"] += 1
        if 주소 == "100.9.9.9":
            raise OSError("꺼져 있다")
        return io.BytesIO(
            b': keepalive\n\n'
            b'data: {"kind":"note","what":"write","title":"\xea\xb0\x80"}\n\n'
            b'data: \xea\xb9\xa8\xec\xa7\x84\n\n'
            b'data: {"kind":"note","what":"delete","title":"\xeb\x82\x98"}\n\n')

    그물이 = 그물("열쇠", 받은.append, 여는이=가짜열기)
    try:
        assert 그물이.맞추기(["100.2.2.2", "100.9.9.9"]) == 2
        # 같은 이웃에 두 번 안 붙는다
        assert 그물이.맞추기(["100.2.2.2"]) == 0, 그물이.붙은수
        끝 = time.monotonic() + 5
        while len(받은) < 2 and time.monotonic() < 끝:
            time.sleep(0.02)
        assert [x["what"] for x in 받은[:2]] == ["write", "delete"], 받은
        assert 받은[0]["title"] == "가", 받은[0]
    finally:
        그물이.그만두기()

    # ★★ **받아서 하는 일이 터져도 귀는 붙어 있는다**
    셈 = {"n": 0}

    def 터지는받기(것):
        셈["n"] += 1
        raise RuntimeError("받다 터졌다")

    둘째 = 그물("열쇠", 터지는받기, 여는이=가짜열기)
    try:
        둘째.맞추기(["100.4.4.4"])
        끝 = time.monotonic() + 5
        while 셈["n"] < 2 and time.monotonic() < 끝:
            time.sleep(0.02)
        assert 셈["n"] >= 2, "하나 터지자 뒤 신호를 못 받았다"
    finally:
        둘째.그만두기()

    print("mesh self-check 통과")


if __name__ == "__main__":
    import sys

    if "--check" in sys.argv:
        _self_check()
