"""새 판이 나왔나 보고, 받아서 깔기 (오너 2026-09-24).

  · 켜면 깃허브에 새 판이 있는지 본다
  · 있으면 **말하고**, 누르면 받아서 깐다

★★ **조용히 갈아 끼우지 않는다.** 쓰던 사람 모르게 프로그램이 바뀌면, 어제 되던
   것이 오늘 안 될 때 무엇이 바뀌었는지 알 길이 없다. 말하고 사람이 누른다.
★★ **받은 것을 셈으로 확인한다.** 굽는 쪽이 `.sha256` 을 같이 올린다 — 안 맞으면
   안 깐다. 받다 끊긴 파일을 실행하는 것이 가장 나쁜 결말이다.
★ 깃허브에 **열쇠 없이** 묻는다(공개 저장소). 그래서 이 파일에는 비밀이 없다.
★ 창고·설정·모델은 앱 폴더 **밖**에 있어 갈아 끼워도 그대로다 — 그것이 이 기능을
  안전하게 만드는 바탕이다(`설치-윈도우.md` 4-1).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

저장소 = "VULCAN-HUB/VC"
새판문 = f"https://api.github.com/repos/{저장소}/releases/latest"
낼곳 = f"https://github.com/{저장소}/releases/latest"
제한초 = 15
받기제한초 = 900


def 판쪼개기(글: str) -> tuple:
    """`v0.5.19` → `(0, 5, 19)`. 숫자로 견줘야 `0.5.9 < 0.5.19` 가 맞는다.

    ★ 글자로 견주면 `"0.5.9" > "0.5.19"` 다 — 판이 열을 넘는 순간 새 판을 놓친다.
    """
    숫자 = re.findall(r"\d+", (글 or "").strip().lstrip("vV"))
    return tuple(int(x) for x in 숫자) or (0,)


def 더새것인가(있는판: str, 나온판: str) -> bool:
    return 판쪼개기(나온판) > 판쪼개기(있는판)


def 내려받을것(자산들: list, 운영체제: str = "") -> dict | None:
    """이 기계에 맞는 파일 하나. 없으면 `None`.

    ★ 맥은 `.dmg`, 윈도우는 설치 `.exe` 를 고른다. `.zip` 은 **뒤로 미룬다** —
      받아도 사람이 풀어 옮겨야 해서 「업데이트」가 안 끝난다.
    """
    운영체제 = 운영체제 or sys.platform
    고를것 = (".dmg",) if 운영체제 == "darwin" else (".exe",)
    for 끝 in 고를것:
        for 것 in 자산들:
            이름 = (것.get("name") or "").lower()
            if 이름.endswith(끝) and not 이름.endswith(".sha256"):
                return 것
    return None


def 셈파일(자산들: list, 이름: str) -> dict | None:
    for 것 in 자산들:
        if (것.get("name") or "") == 이름 + ".sha256":
            return 것
    return None


def 물어보기(지금판: str, 부르기=None) -> dict:
    """새 판이 있나. `{"있나", "판", "받을곳", "쪽", "왜"}`.

    ★★ **못 물어봐도 켜는 것을 막지 않는다.** 인터넷이 없거나 깃허브가 느릴 때
       프로그램이 안 뜨면, 업데이트 확인이 프로그램보다 중해지는 꼴이다.
    """
    부르기 = 부르기 or _열기
    try:
        글 = 부르기(새판문)
        난것 = json.loads(글)
    except Exception as e:
        return {"있나": False, "왜": f"못 물어봤다: {type(e).__name__}"}
    if not isinstance(난것, dict):
        return {"있나": False, "왜": "못 알아들을 답이 왔다"}
    나온판 = str(난것.get("tag_name") or "").strip()
    if not 나온판:
        return {"있나": False, "왜": "낸 판이 아직 없다"}
    if not 더새것인가(지금판, 나온판):
        return {"있나": False, "판": 나온판, "왜": ""}
    자산들 = 난것.get("assets") or []
    받을것 = 내려받을것(자산들)
    return {"있나": True, "판": 나온판, "쪽": 난것.get("html_url") or 낼곳,
            "받을곳": (받을것 or {}).get("browser_download_url") or "",
            "이름": (받을것 or {}).get("name") or "",
            "셈곳": ((셈파일(자산들, (받을것 or {}).get("name") or "") or {})
                   .get("browser_download_url") or ""),
            "왜": "" if 받을것 else "이 기계에 맞는 파일이 그 판에 없다"}


def _열기(주소: str, 초: int = 제한초) -> str:
    요청 = urllib.request.Request(주소, headers={
        "Accept": "application/vnd.github+json", "User-Agent": "VC"})
    with urllib.request.urlopen(요청, timeout=초) as r:
        return r.read().decode("utf-8", "replace")


def 받기(주소: str, 낼자리: Path, 셈주소: str = "", 알림=None,
       열기=None, 멈춤=None) -> dict:
    """파일을 받고 **셈을 맞춰 본다.** `{"됐나", "자리", "왜"}`.

    ★★ 셈이 안 맞으면 **지우고 안 깐다.** 받다 끊긴 것을 실행하는 것이 가장 나쁘다.
    """
    열기 = 열기 or (lambda 주소: urllib.request.urlopen(
        urllib.request.Request(주소, headers={"User-Agent": "VC"}), timeout=받기제한초))
    낼자리 = Path(낼자리)
    낼자리.parent.mkdir(parents=True, exist_ok=True)
    도중 = 낼자리.with_suffix(낼자리.suffix + ".part")   # 다 받기 전엔 제 이름을 안 준다
    셈 = hashlib.sha256()
    받은 = 0
    멈췄나 = False
    # ★★ **연 채로 지우지 않는다.** 맥·리눅스는 열린 파일도 지워지지만 **윈도우는
    #   안 된다** — `PermissionError: [WinError 32] 다른 프로세스가 파일을 사용 중`
    #   으로 터진다. 그래서 `with` 를 빠져나온 **뒤에** 치운다(윈도우 실기가 잡았다).
    try:
        with 열기(주소) as r, open(도중, "wb") as f:
            전체 = int(r.headers.get("Content-Length") or 0) if hasattr(r, "headers") else 0
            while True:
                if 멈춤 is not None and 멈춤():
                    멈췄나 = True
                    break
                덩이 = r.read(1 << 20)
                if not 덩이:
                    break
                f.write(덩이)
                셈.update(덩이)
                받은 += len(덩이)
                if 알림 is not None and 전체:
                    알림(받은, 전체)
    except Exception as e:
        _치우기(도중)
        return {"됐나": False, "왜": f"받다 막혔다: {type(e).__name__}: {e}"}
    if 멈췄나:
        _치우기(도중)
        return {"됐나": False, "왜": "멈추라고 했다"}

    # ★★ **못 맞춰 본 것은 「맞았다」가 아니다.** 셈 파일이 없거나 못 읽으면
    #   여태 **조용히 넘어갔다** — 받는 쪽은 맞춰 본 줄 안다.
    #   막지는 않는다(그러면 셈을 안 낸 옛 판으로 영영 업데이트를 못 한다).
    #   대신 **못 맞췄다고 말한다.** 잠잠한 것이 제일 나쁘다.
    못맞춘까닭 = ""
    if 셈주소:
        try:
            적힌 = _열기(셈주소, 받기제한초).split()[0].lower()
        except Exception as e:
            적힌, 못맞춘까닭 = "", f"셈 파일을 못 읽었다({type(e).__name__})"
        if 적힌 and 적힌 != 셈.hexdigest():
            _치우기(도중)
            return {"됐나": False, "왜": "받은 파일의 셈이 안 맞는다 — 받다 끊겼거나 바뀌었다"}
        if not 적힌 and not 못맞춘까닭:
            못맞춘까닭 = "셈 파일이 비어 있다"
    else:
        못맞춘까닭 = "그 판에 셈 파일이 없다"
    도중.replace(낼자리)
    return {"됐나": True, "자리": str(낼자리),
            "왜": "", "못맞춤": 못맞춘까닭}


def _치우기(자리: Path, 몇번: int = 5) -> None:
    """받다 만 것을 지운다. **윈도우는 곧바로 안 지워질 때가 있다.**

    ★ 백신이 방금 닫힌 파일을 잠깐 붙들고 있으면 `WinError 32` 가 난다 —
      몇 번 쉬었다 다시 해 본다. 끝내 못 지워도 **부르는 쪽을 막지는 않는다**
      (`.part` 라 목록에도 안 뜨고, 다음에 덮어쓴다).
    """
    import time as _때

    for 번 in range(몇번):
        try:
            자리.unlink(missing_ok=True)
            return
        except OSError:
            _때.sleep(0.1 * (번 + 1))


def 깔기명령(자리: str, 운영체제: str = "") -> list[str]:
    """받은 것을 여는 명령. **우리가 직접 덮어쓰지 않는다.**

    ★★ 돌고 있는 제 몸을 스스로 갈아 끼우면 반쯤 갈린 채로 죽을 수 있다.
       윈도우는 **설치 프로그램**이 돌던 VC 를 닫고 갈아 끼운다(`VC.iss`).
       맥은 dmg 를 **열어 준다** — 끌어다 놓는 것은 사람이 한다(가장 안전하다).
    """
    운영체제 = 운영체제 or sys.platform
    if 운영체제 == "darwin":
        return ["open", 자리]
    if os.name == "nt":
        return [자리]
    return ["xdg-open", 자리]


def _self_check() -> None:
    import io
    import tempfile

    # ★★ **숫자로 견준다** — 글자로 견주면 0.5.9 > 0.5.19 가 되어 새 판을 놓친다
    assert 판쪼개기("v0.5.19") == (0, 5, 19) and 판쪼개기("0.5.9") == (0, 5, 9)
    assert 더새것인가("0.5.9", "0.5.19"), "열을 넘는 판을 못 알아본다"
    assert 더새것인가("0.5.19", "0.6.0") and not 더새것인가("0.5.19", "0.5.19")
    assert not 더새것인가("0.5.19", "0.5.18")
    assert 판쪼개기("") == (0,) and 판쪼개기("이상한판") == (0,)

    # 이 기계에 맞는 것을 고른다
    자산 = [{"name": "VC.zip"}, {"name": "VC-mac-v0.5.20.dmg"},
          {"name": "VC-설치-0.5.20.exe"}, {"name": "VC-설치-0.5.20.exe.sha256"}]
    assert 내려받을것(자산, "darwin")["name"].endswith(".dmg")
    assert 내려받을것(자산, "win32")["name"] == "VC-설치-0.5.20.exe"
    # ★ `.sha256` 을 본체로 고르면 안 된다
    assert not 내려받을것(자산, "win32")["name"].endswith(".sha256")
    assert 내려받을것([{"name": "VC.zip"}], "darwin") is None
    assert 셈파일(자산, "VC-설치-0.5.20.exe")["name"].endswith(".sha256")

    # --- 물어보기 ---
    답 = json.dumps({"tag_name": "v0.5.20", "html_url": "https://x/y",
                    "assets": [{"name": "VC-mac-v0.5.20.dmg",
                                "browser_download_url": "https://x/a.dmg"},
                               {"name": "VC-mac-v0.5.20.dmg.sha256",
                                "browser_download_url": "https://x/a.dmg.sha256"}]})
    난것 = 물어보기("0.5.19", lambda 주소: 답)
    if sys.platform == "darwin":
        assert 난것["있나"] and 난것["판"] == "v0.5.20", 난것
        assert 난것["받을곳"].endswith(".dmg") and 난것["셈곳"].endswith(".sha256"), 난것
    assert not 물어보기("0.5.20", lambda 주소: 답)["있나"], "같은 판인데 새것이라 한다"
    assert not 물어보기("9.9.9", lambda 주소: 답)["있나"]

    # ★★ **못 물어봐도 켜는 것을 막지 않는다**
    def _터짐(주소):
        raise OSError("인터넷 없다")

    탈 = 물어보기("0.5.19", _터짐)
    assert 탈["있나"] is False and "못 물어봤다" in 탈["왜"], 탈
    assert not 물어보기("0.5.19", lambda 주소: "깨진 글")["있나"]
    assert 물어보기("0.5.19", lambda 주소: "{}")["왜"] == "낸 판이 아직 없다"

    # --- 받기: 셈이 맞을 때와 안 맞을 때 ---
    몸 = b"VC-\xea\xb0\x80\xeb\x82\x98" * 1000
    참셈 = hashlib.sha256(몸).hexdigest()

    class _응답(io.BytesIO):
        headers = {"Content-Length": str(len(몸))}

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    with tempfile.TemporaryDirectory() as tmp:
        낼것 = Path(tmp) / "받은것.dmg"
        진행 = []
        옛열기 = globals()["_열기"]
        globals()["_열기"] = lambda 주소, 초=제한초: 참셈 + "  받은것.dmg"
        try:
            난것 = 받기("https://x/a", 낼것, "https://x/a.sha256",
                     알림=lambda a, b: 진행.append(a),
                     열기=lambda 주소: _응답(몸))
            assert 난것["됐나"] and 낼것.exists(), 난것
            assert 낼것.read_bytes() == 몸
            assert 진행 and 진행[-1] == len(몸), 진행
            # ★★ **셈이 안 맞으면 지우고 안 깐다**
            낼것.unlink()
            globals()["_열기"] = lambda 주소, 초=제한초: "0" * 64 + "  받은것.dmg"
            난것 = 받기("https://x/a", 낼것, "https://x/a.sha256",
                     열기=lambda 주소: _응답(몸))
            assert not 난것["됐나"] and "셈이 안 맞는다" in 난것["왜"], 난것
            assert not 낼것.exists(), "셈이 틀렸는데 파일을 남겼다"
            assert not list(낼것.parent.glob("*.part")), "받다 만 것이 남았다"
            # 멈추면 자국을 안 남긴다
            # ★★ **멈출 때 연 채로 지우지 않는다** — 윈도우는 열린 파일을 못 지운다
            #   (`WinError 32`). 윈도우 실기가 잡은 자리다.
            열린채로지웠나 = []

            class _못지우는파일(io.BytesIO):
                headers = {"Content-Length": str(len(몸))}

                def __enter__(self):
                    return self

                def __exit__(self, *a):
                    _열림["열렸나"] = False
                    return False

            _열림 = {"열렸나": False}
            옛열기파일 = open

            난것 = 받기("https://x/a", 낼것, "", 멈춤=lambda: True,
                     열기=lambda 주소: _응답(몸))
            assert not 난것["됐나"] and "멈추라고" in 난것["왜"], 난것
            assert not 낼것.exists() and not list(낼것.parent.glob("*.part"))
            # 소스로도 못 박는다 — `with` 안에서 지우면 윈도우에서 또 터진다
            import inspect as _본다받기

            _소스받기 = _본다받기.getsource(받기)
            _안쪽 = _소스받기[_소스받기.index("with 열기("):_소스받기.index("except Exception")]
            assert "unlink" not in _안쪽 and "_치우기" not in _안쪽, \
                "파일을 연 채로 지운다 — 윈도우에서 WinError 32 로 터진다"
        finally:
            globals()["_열기"] = 옛열기

    # ★ 우리가 직접 덮어쓰지 않는다 — 여는 것까지만 한다
    assert 깔기명령("/tmp/a.dmg", "darwin") == ["open", "/tmp/a.dmg"]

    print("update self-check 통과")


if __name__ == "__main__":
    if "--check" in sys.argv:
        _self_check()
