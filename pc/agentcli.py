"""에이전트 CLI — **남의 에이전트를 빌려 쓴다.** 화면은 안 쓴다.

클로드 코드·Codex 는 이미 껍데기(도구·파일 고치기·git·검사 돌리기)를 다 갖췄다.
우리가 그것을 다시 만들 이유가 없다 — **프로젝트 폴더에서 돌리고, 무엇이 바뀌었는지
git 으로 재서, 창고에 적립**하면 된다. 키가 없어도 된다(사람이 이미 로그인해 뒀다).

    돌리기(프로젝트, 지시, 손="claude")  →  {"됐나", "끝난코드", "바뀐파일", "차이", …}

★★ **성공을 「말」로 재지 않는다.** CLI 가 「완료했습니다」라고 해도 아무것도 안 바뀌었을
   수 있다. **끝난 코드 + `git status` + `git diff`** 로 잰다 — 한 일과 한 말은 다르다.

★★ **자동으로 되돌리지 않는다.** `git reset --hard` 를 우리가 부르면, 에이전트를 돌리기
   **전에 오너가 고쳐 둔 것까지** 날아간다. 그래서 **돌리기 전 상태를 적어 두고**
   무엇이 원래 더러웠는지 표시만 한다 — 되돌릴지는 사람이 정한다.

★★ **손은 갈아 끼운다.** CLI 는 남의 것이라 판이 올라가면 명령이 바뀐다. 그 변덕을
   **어댑터 한 자리**에 가둔다. `fake` 손이 있어 **CLI 가 안 깔려 있어도** 전 경로를 잰다.

★ 되돌리기 밑천은 git 이다 — `hermes.차리기` 가 `git init` 을 먼저 하는 까닭이 여기다.
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

import codefiles
import hermes

기본제한초 = 900          # 15분. 넘으면 끊는다 — 영영 기다리면 창이 굳는다
차이최대 = 200_000        # 사람에게 보일 차이의 최대 길이


class 손:
    """CLI 하나를 어떻게 부르는가. **여기만 고치면 CLI 판올림을 흡수한다.**"""

    이름 = ""
    실행파일 = ""

    def 있나(self) -> bool:
        import shutil

        return bool(self.실행파일) and shutil.which(self.실행파일) is not None

    def 명령(self, 지시: str, 읽기전용: bool = False) -> list[str]:
        """이 CLI 를 부르는 명령.

        ★★ `읽기전용` 은 **보는 손**(리뷰)을 위한 것이다. 리뷰가 파일을 고치면
           짓는 손의 일과 섞여 무엇이 누구 탓인지 알 수 없게 된다.
        """
        raise NotImplementedError

    def 끝말(self, 나온것: str) -> str:
        """CLI 가 마지막으로 한 말. 보고에 쓴다 — **성공 판정에는 안 쓴다.**"""
        줄 = [x for x in (나온것 or "").splitlines() if x.strip()]
        return 줄[-1][:500] if 줄 else ""


class 클로드(손):
    """클로드 코드. `-p` 가 한 번 돌리고 끝나는 모습이다.

    ★ 깃발은 **실제로 깔고 한 번 돌려 봐야** 확정된다(이 맥엔 아직 없다).
      여기 모아 둔 까닭이 그것이다 — 틀리면 이 줄만 고친다.
    """

    이름 = "claude"
    실행파일 = "claude"

    def 명령(self, 지시: str, 읽기전용: bool = False) -> list[str]:
        # ★★ **읽기전용을 깃발로 못 박지 않는다.** 확인 안 된 깃발을 넣으면 안 도는
        #   명령이 된다 — 이 맥엔 아직 안 깔려 실기로 못 쟀다. 대신 **말로 시키고,
        #   돌린 뒤 git 으로 잰다**(`돌리기` 가 고쳤으면 탈로 잡는다).
        #   깔고 확인되면 여기 한 줄만 고친다.
        return [self.실행파일, "-p", 지시, "--output-format", "json"]


class 코덱스(손):
    """Codex. `exec` 가 비대화식이고 **기본이 읽기 전용 샌드박스**다.

    ★ 고치게 하려면 `--sandbox workspace-write` 가 필요하다 — 권한을 **필요한 만큼만** 연다.
    """

    이름 = "codex"
    실행파일 = "codex"

    def 명령(self, 지시: str, 읽기전용: bool = False) -> list[str]:
        # ★ 기본이 읽기 전용이라 **보는 손일 때는 아무 깃발도 안 준다** — 문서가 그렇다.
        if 읽기전용:
            return [self.실행파일, "exec", 지시]
        return [self.실행파일, "exec", "--sandbox", "workspace-write", 지시]


class 가짜(손):
    """CLI 없이 **전 경로를 재는** 손. 시킨 대로 파일을 하나 고치고 끝난다.

    ★★ 이것이 있어야 CLI 가 안 깔린 기계에서도 프로세스·스트림·차이·적립까지 잰다.
       실제 CLI 는 나중에 깔고 어댑터만 켜면 된다.
    """

    이름 = "fake"
    실행파일 = "python3"

    def __init__(self, 고칠파일: str = "", 새글: str = "", 끝난코드: int = 0) -> None:
        self.고칠파일, self.새글, self._코드 = 고칠파일, 새글, 끝난코드

    def 있나(self) -> bool:
        return True

    def 명령(self, 지시: str, 읽기전용: bool = False) -> list[str]:
        # ★ 지시를 **따옴표 안에 그대로 박으면 안 된다.** 여러 줄·따옴표가 든 지시가
        #   오면 스크립트가 깨진다(협업 리뷰 지시가 실제로 그랬다). `repr` 로 감싼다.
        한줄 = " ".join((지시 or "").split())[:60]
        조각 = ["import sys", f"print('가짜 손이 돌았다: ' + {한줄!r})"]
        if self.고칠파일 and not 읽기전용:
            조각.append(
                f"open({self.고칠파일!r}, 'w', encoding='utf-8').write({self.새글!r})")
        조각.append(f"sys.exit({self._코드})")
        import sys as _sys

        return [_sys.executable, "-c", "\n".join(조각)]


손들: dict[str, type[손] | 손] = {"claude": 클로드, "codex": 코덱스, "fake": 가짜}


def 손고르기(이름: str) -> 손 | None:
    것 = 손들.get((이름 or "").strip().lower())
    if 것 is None:
        return None
    return 것 if isinstance(것, 손) else 것()


def _git(자리: Path, *인자: str) -> str:
    try:
        난것 = subprocess.run(["git", "-C", str(자리), *인자],
                            capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return ""
    return 난것.stdout if 난것.returncode == 0 else ""


def 지금상태(자리: Path) -> dict:
    """돌리기 **전** 기준점. 머리와 **이미 더러운 파일들**을 적어 둔다.

    ★★ 더러운 것을 적어 두지 않으면, 나중에 「에이전트가 고친 것」과 「오너가 이미
       고쳐 둔 것」을 가를 수가 없다 — 그러면 되돌리기가 위험해진다.
    """
    머리 = _git(자리, "rev-parse", "HEAD").strip()
    # ★★ **`-z` 로 받는다.** 그냥 받으면 git 이 한글 파일 이름을 **8진수로 이스케이프**해서
    #   (`\354\230\244…`) 이름이 안 맞는다 — 그러면 「원래 더럽던 것」을 못 가른다.
    #   `-z` 는 NUL 로 끊고 따옴표·이스케이프를 아예 안 쓴다(검사가 잡았다 · 2026-09-21).
    더러운 = set()
    for 조각 in _git(자리, "status", "--porcelain", "-z").split("\0"):
        길 = 조각[3:].strip() if len(조각) > 3 else ""
        if 길:
            더러운.add(길)
    더러운 = sorted(더러운)
    return {"머리": 머리, "더러운파일": 더러운, "git": bool(_git(자리, "rev-parse", "--git-dir"))}


def 돌리기(프로젝트: str, 지시: str, 손이름: str = "claude", 제한초: int = 기본제한초,
        뿌리: Path | None = None, 멈춤=None, 손물건: 손 | None = None,
        읽기전용: bool = False) -> dict:
    """에이전트 CLI 를 프로젝트 폴더에서 돌린다.

    돌려주는 것:
        `{"손", "됐나", "끝난코드", "나온말", "탈말", "끝말", "바뀐파일",
          "원래더럽던것", "차이", "든시간", "왜"}`
    """
    지시 = (지시 or "").strip()
    if not hermes.영문이름인가(프로젝트):
        return {"손": 손이름, "됐나": False, "왜": "그런 프로젝트가 없다"}
    if not 지시:
        return {"손": 손이름, "됐나": False, "왜": "지시가 비었다"}
    자리 = codefiles.프로젝트뿌리(프로젝트, 뿌리)
    if not 자리.is_dir():
        return {"손": 손이름, "됐나": False, "왜": "그런 프로젝트가 없다"}

    그손 = 손물건 or 손고르기(손이름)
    if 그손 is None:
        return {"손": 손이름, "됐나": False, "왜": f"모르는 손이다: {손이름}"}
    if not 그손.있나():
        return {"손": 그손.이름, "됐나": False,
                "왜": f"`{그손.실행파일}` 이 이 기계에 없다 — 먼저 깔아야 한다"}

    전 = 지금상태(자리)
    t = time.perf_counter()
    나온말 = 탈말 = ""
    끝난코드 = -1
    끊겼나 = False
    try:
        판 = subprocess.Popen(그손.명령(지시, 읽기전용), cwd=str(자리),
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    except (OSError, ValueError) as e:
        return {"손": 그손.이름, "됐나": False, "왜": f"못 띄웠다: {type(e).__name__}"}

    try:
        while True:
            try:
                나온말, 탈말 = 판.communicate(timeout=1.0)
                끝난코드 = 판.returncode
                break
            except subprocess.TimeoutExpired:
                if time.perf_counter() - t > 제한초 or (멈춤 is not None and 멈춤()):
                    끊겼나 = True
                    판.kill()
                    나온말, 탈말 = 판.communicate()
                    끝난코드 = 판.returncode
                    break
    except Exception as e:                       # 무슨 일이 나도 창이 죽으면 안 된다
        try:
            판.kill()
        except Exception:
            pass
        return {"손": 그손.이름, "됐나": False, "왜": f"돌리다 터졌다: {type(e).__name__}: {e}"}
    든시간 = time.perf_counter() - t

    후 = 지금상태(자리)
    바뀐 = [f for f in 후["더러운파일"] if f not in 전["더러운파일"]]
    원래 = [f for f in 후["더러운파일"] if f in 전["더러운파일"]]
    차 = _git(자리, "diff")[:차이최대] if 후["git"] else ""

    # ★★ **성공은 말이 아니라 끝난 코드로 잰다.** 바뀐 것이 없어도 성공일 수 있다
    #   (「고칠 게 없다」가 옳은 답일 때가 있다). 그래서 둘을 따로 돌려준다.
    왜 = ""
    if 끊겼나:
        왜 = "제한 시간이 지났거나 멈추라고 했다"
    elif 끝난코드 != 0:
        왜 = f"끝난 코드가 {끝난코드} 다"
    # ★★ **읽기전용이라 해 놓고 고쳤으면 탈이다.** 말로만 시킨 손도 있으니
    #   **git 으로 잰다** — 보는 손이 고치면 누구 탓인지 못 가린다.
    if 읽기전용 and 바뀐:
        왜 = f"읽기만 하라 했는데 {len(바뀐)}개를 고쳤다: {' · '.join(바뀐[:3])}"
    return {"손": 그손.이름,
            "됐나": (끝난코드 == 0 and not 끊겼나 and not (읽기전용 and 바뀐)),
            "끝난코드": 끝난코드,
            "나온말": 나온말 or "", "탈말": 탈말 or "", "끝말": 그손.끝말(나온말),
            "바뀐파일": 바뀐, "원래더럽던것": 원래, "차이": 차,
            "든시간": round(든시간, 1), "끊겼나": 끊겼나, "머리": 전["머리"],
            "읽기전용": 읽기전용, "왜": 왜}


def 사람말(난것: dict) -> str:
    """돌린 결과를 사람이 읽는 한 덩이로."""
    if not 난것:
        return "아무 일도 안 했다"
    if 난것.get("왜") and not 난것.get("끝난코드"):
        return f"못 돌렸어 — {난것['왜']}"
    머리 = [f"{난것.get('손')} 가 {난것.get('든시간', 0)}초 돌았어 "
          f"({'됐다' if 난것.get('됐나') else '탈났다'}"
          + (f" — {난것['왜']}" if 난것.get("왜") else "") + ")"]
    바뀐 = 난것.get("바뀐파일") or []
    머리.append(f"바뀐 파일 {len(바뀐)}개" + (f": {' · '.join(바뀐[:5])}" if 바뀐 else " — 없다"))
    if 난것.get("원래더럽던것"):
        머리.append(f"★ 돌리기 전부터 고쳐져 있던 것 {len(난것['원래더럽던것'])}개 — "
                  f"되돌릴 때 같이 날리지 않게 조심: {' · '.join(난것['원래더럽던것'][:5])}")
    if 난것.get("끝말"):
        머리.append(f"마지막 말: {난것['끝말'][:200]}")
    return "\n".join(머리)


def _self_check() -> None:
    import tempfile

    # 손 고르기
    assert 손고르기("claude").이름 == "claude" and 손고르기("CODEX").이름 == "codex"
    assert 손고르기("없는손") is None
    assert "-p" in 클로드().명령("일해라") and "일해라" in 클로드().명령("일해라")
    # ★ Codex 는 권한을 **필요한 만큼만** 연다
    assert "--sandbox" in 코덱스().명령("일해라"), 코덱스().명령("일해라")
    assert "workspace-write" in 코덱스().명령("일해라")

    with tempfile.TemporaryDirectory() as tmp:
        뿌리 = Path(tmp) / "projects"
        자리 = 뿌리 / "CliApp"
        자리.mkdir(parents=True)
        (자리 / "a.py").write_text("x = 1\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(자리), "init", "-q"], capture_output=True)
        subprocess.run(["git", "-C", str(자리), "add", "-A"], capture_output=True)
        subprocess.run(["git", "-C", str(자리), "-c", "user.name=T",
                        "-c", "user.email=t@t", "commit", "-qm", "첫"], capture_output=True)

        # --- 아무것도 안 바꾸는 손 ---
        난것 = 돌리기("CliApp", "가만히 있어라", 뿌리=뿌리, 손물건=가짜())
        assert 난것["됐나"] and 난것["끝난코드"] == 0, 난것
        assert 난것["바뀐파일"] == [], 난것
        assert "가짜 손이 돌았다" in 난것["나온말"], 난것["나온말"]

        # --- 파일을 고치는 손 → git 이 잡아낸다 ---
        난것 = 돌리기("CliApp", "a.py 고쳐라", 뿌리=뿌리,
                   손물건=가짜(str(자리 / "a.py"), "x = 2\n"))
        assert 난것["됐나"], 난것
        assert 난것["바뀐파일"] == ["a.py"], 난것["바뀐파일"]
        assert "-x = 1" in 난것["차이"] and "+x = 2" in 난것["차이"], 난것["차이"]

        # ★★ **돌리기 전부터 더럽던 것과 가른다** — 안 가르면 되돌릴 때 오너 작업이 날아간다
        (자리 / "오너가고친것.py").write_text("사람이 쓴 것\n", encoding="utf-8")
        난것 = 돌리기("CliApp", "b.py 만들어라", 뿌리=뿌리,
                   손물건=가짜(str(자리 / "b.py"), "y = 1\n"))
        assert 난것["바뀐파일"] == ["b.py"], 난것["바뀐파일"]
        assert "오너가고친것.py" in 난것["원래더럽던것"], 난것["원래더럽던것"]
        assert "조심" in 사람말(난것), 사람말(난것)

        # ★★ **성공을 말로 재지 않는다** — 「됐다」고 해도 끝난 코드가 0 이 아니면 탈이다
        난것 = 돌리기("CliApp", "실패해라", 뿌리=뿌리, 손물건=가짜(끝난코드=3))
        assert not 난것["됐나"] and 난것["끝난코드"] == 3, 난것
        assert "끝난 코드가 3" in 난것["왜"], 난것["왜"]

        # 제한 시간 — 영영 기다리지 않는다
        import sys as _sys

        class _느린손(손):
            이름, 실행파일 = "느린", _sys.executable

            def 있나(self):
                return True

            def 명령(self, 지시, 읽기전용=False):
                return [_sys.executable, "-c", "import time; time.sleep(30)"]

        t0 = time.perf_counter()
        난것 = 돌리기("CliApp", "오래 걸려라", 뿌리=뿌리, 제한초=2, 손물건=_느린손())
        assert 난것["끊겼나"] and not 난것["됐나"], 난것
        assert time.perf_counter() - t0 < 12, "제한 시간을 안 지킨다"

        # 멈추라고 하면 멈춘다
        난것 = 돌리기("CliApp", "멈춰라", 뿌리=뿌리, 멈춤=lambda: True, 손물건=_느린손())
        assert 난것["끊겼나"], 난것

        # ★★ **보는 손은 파일을 고치면 안 된다.** 읽기전용이라 해 놓고 고쳤으면 탈로 잡는다 —
        #   리뷰가 고치면 짓는 손의 일과 섞여 누구 탓인지 못 가린다.
        난것 = 돌리기("CliApp", "보기만 해라", 뿌리=뿌리, 읽기전용=True,
                   손물건=가짜(str(자리 / "a.py"), "몰래 고침\n"))
        assert 난것["됐나"], 난것            # 가짜 손은 읽기전용이면 안 고친다
        assert 난것["바뀐파일"] == [], 난것["바뀐파일"]
        # 말을 안 듣는 손이면 **git 이 잡는다**
        class _말안듣는손(손):
            이름, 실행파일 = "말안듣", "python3"

            def 있나(self):
                return True

            def 명령(self, 지시, 읽기전용=False):
                import sys as _s
                글 = "open(%r, 'w').write('몰래')" % str(자리 / "c.py")
                return [_s.executable, "-c", 글]

        난것 = 돌리기("CliApp", "보기만 해라", 뿌리=뿌리, 읽기전용=True, 손물건=_말안듣는손())
        assert not 난것["됐나"] and "읽기만 하라 했는데" in 난것["왜"], 난것
        (자리 / "c.py").unlink(missing_ok=True)

        # 코덱스는 **보는 손일 때 샌드박스 깃발을 안 준다**(기본이 읽기 전용이다)
        assert "--sandbox" not in 코덱스().명령("보기만", 읽기전용=True)
        assert "--sandbox" in 코덱스().명령("고쳐라", 읽기전용=False)

        # 없는 손·없는 프로젝트
        assert not 돌리기("CliApp", "일해라", "없는손", 뿌리=뿌리)["됐나"]
        assert 돌리기("없는것", "일해라", 뿌리=뿌리, 손물건=가짜())["왜"] == "그런 프로젝트가 없다"
        assert 돌리기("CliApp", "", 뿌리=뿌리, 손물건=가짜())["왜"] == "지시가 비었다"

        # 안 깔린 CLI 는 **까닭을 말한다** — 조용히 실패하지 않는다
        class _없는손(손):
            이름, 실행파일 = "없는놈", "vc-없는-실행파일-zzz"

        난것 = 돌리기("CliApp", "일해라", 뿌리=뿌리, 손물건=_없는손())
        assert not 난것["됐나"] and "먼저 깔아야 한다" in 난것["왜"], 난것

    print("agentcli self-check 통과")


if __name__ == "__main__":
    import sys

    if "--check" in sys.argv:
        _self_check()
