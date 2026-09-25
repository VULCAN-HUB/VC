"""테일스케일 주소 — 폰이 VC 에 붙는 길 (오너 결정 18 · 결정 16 구현).

★★ 폰 짝짓기 QR 에는 **테일스케일 주소**를 담는다. 집 와이파이 주소를 담으면 폰이 다른 와이파이나
이동통신으로 옮겨 가는 순간 「PC 에 못 닿았어」가 된다(2026-09-15 아이폰 실기). 테일스케일 주소는 어디서나 같다.

꺼져 있으면 `None` 을 준다 — **조용히 집 주소로 넘어가지 않는다**(결정 21). 부르는 쪽이 알리고 사람이 고르게 한다.

찾는 차례: 테일스케일 명령(`ip -4`) → 인터페이스 목록에서 **터널 인터페이스에 붙은** 100.64.0.0/10 주소.
※ 100.64.0.0/10 은 통신사 CGNAT 도 쓰는 대역이다. 일반 인터페이스(en0 등)에 그 주소가 붙어도 테일스케일이 아니다 —
  인터페이스 이름(utun · tailscale · 「Tailscale」 어댑터)까지 봐야 착각하지 않는다.
"""

from __future__ import annotations

import paths

import ipaddress
import os
import re
import shutil
import subprocess
import sys
from typing import Callable

_CGNAT = ipaddress.ip_network("100.64.0.0/10")
_IP4 = re.compile(r"(?<![\d.])(\d{1,3}(?:\.\d{1,3}){3})(?![\d.])")

Runner = Callable[[list[str]], "str | None"]


def _run(cmd: list[str]) -> str | None:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=4, **paths.창안띄우기())
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout if r.returncode == 0 else None


def _테일넷주소(글: str | None) -> str | None:
    """글에서 처음 나오는 100.64.0.0/10 주소."""
    for m in _IP4.finditer(글 or ""):
        try:
            ip = ipaddress.ip_address(m.group(1))
        except ValueError:
            continue
        if ip in _CGNAT:
            return str(ip)
    return None


def _명령들() -> list[str]:
    후보: list[str] = []
    if sys.platform == "darwin":
        후보.append("/Applications/Tailscale.app/Contents/MacOS/Tailscale")
    if sys.platform.startswith("win"):
        for base in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)")):
            if base:
                후보.append(os.path.join(base, "Tailscale", "tailscale.exe"))
    if (찾음 := shutil.which("tailscale")):
        후보.append(찾음)
    return [c for c in 후보 if os.path.exists(c)]


def _터널인터페이스주소(목록: str | None, 윈도우: bool) -> str | None:
    """인터페이스 목록에서 **터널 인터페이스에 붙은** 테일넷 주소만."""
    if not 목록:
        return None
    if 윈도우:
        # ipconfig: 「... adapter Tailscale:」 머리 아래 줄들이 그 어댑터 것이다
        덩이 = re.split(r"\r?\n(?=\S)", 목록)
        for d in 덩이:
            if "tailscale" in (d.splitlines() or [""])[0].lower():
                if (ip := _테일넷주소(d)):
                    return ip
        return None
    # ifconfig: 줄머리가 「이름:」 이면 새 인터페이스
    덩이 = re.split(r"\n(?=[A-Za-z0-9]+:)", 목록)
    for d in 덩이:
        이름 = d.split(":", 1)[0].strip().lower()
        if 이름.startswith(("utun", "tailscale")):
            if (ip := _테일넷주소(d)):
                return ip
    return None


def tailscale_ip(run: Runner = _run, 명령들: list[str] | None = None, 윈도우: bool | None = None) -> str | None:
    """이 컴퓨터의 테일스케일 IPv4. 꺼져 있거나 없으면 `None`."""
    for c in (명령들 if 명령들 is not None else _명령들()):
        if (ip := _테일넷주소(run([c, "ip", "-4"]))):
            return ip
    윈도우 = sys.platform.startswith("win") if 윈도우 is None else 윈도우
    return _터널인터페이스주소(run(["ipconfig"] if 윈도우 else ["ifconfig"]), 윈도우)


def _self_check() -> None:
    가짜 = "100.101.2.3"          # 시험용 가짜 주소
    # 명령이 답하면 그것
    assert tailscale_ip(lambda c: 가짜 + "\n" if c[1:] == ["ip", "-4"] else None, ["ts"], 윈도우=False) == 가짜
    # 명령이 「꺼짐」이면 인터페이스 목록에서 — 터널 인터페이스에 붙은 것만
    맥목록 = ("lo0: flags=8049<UP,LOOPBACK> mtu 16384\n\tinet 127.0.0.1 netmask 0xff000000\n"
            "en0: flags=8863<UP,BROADCAST> mtu 1500\n\tinet 192.168.1.9 netmask 0xffffff00\n"
            "utun4: flags=8051<UP,POINTOPOINT> mtu 1280\n\tinet " + 가짜 + " --> " + 가짜 + " netmask 0xffffffff\n")
    assert tailscale_ip(lambda c: 맥목록 if c == ["ifconfig"] else None, ["ts"], 윈도우=False) == 가짜
    # ★ 일반 인터페이스에 붙은 통신사 CGNAT 주소는 테일스케일이 아니다
    통신사 = "en0: flags=8863<UP,BROADCAST> mtu 1500\n\tinet 100.70.0.5 netmask 0xffc00000\n"
    assert tailscale_ip(lambda c: 통신사 if c == ["ifconfig"] else None, [], 윈도우=False) is None, \
        "일반 인터페이스의 CGNAT 주소를 테일스케일로 착각한다"
    # 윈도우 ipconfig
    창목록 = ("Windows IP Configuration\r\n\r\n"
            "Ethernet adapter Ethernet:\r\n\r\n   IPv4 Address. . . . . . . . . . . : 192.168.0.20\r\n\r\n"
            "Unknown adapter Tailscale:\r\n\r\n   IPv4 Address. . . . . . . . . . . : " + 가짜 + "\r\n")
    assert tailscale_ip(lambda c: 창목록 if c == ["ipconfig"] else None, [], 윈도우=True) == 가짜
    # 아무것도 없으면 None — 집 주소로 조용히 넘어가지 않는다
    assert tailscale_ip(lambda c: None, [], 윈도우=False) is None
    # 대역 끝
    assert _테일넷주소("100.63.255.255") is None and _테일넷주소("100.128.0.1") is None
    assert _테일넷주소("100.64.0.1") == "100.64.0.1" and _테일넷주소("100.127.255.254") == "100.127.255.254"
    print("tailnet self-check 통과")


if __name__ == "__main__":
    if "--check" in sys.argv:
        _self_check()
    else:
        print(tailscale_ip() or "테일스케일 꺼짐")
