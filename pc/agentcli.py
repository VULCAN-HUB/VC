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

import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

import codefiles
import hermes

기본제한초 = 900          # 15분. 넘으면 끊는다 — 영영 기다리면 창이 굳는다
차이최대 = 200_000        # 사람에게 보일 차이의 최대 길이

# ★★ **굽힌 앱은 셸 PATH 를 못 받는다.** Finder 로 띄운 `.app` 은 launchd 기본
#    (`/usr/bin:/bin:/usr/sbin:/sbin`) 만 받아서 `/opt/homebrew/bin/claude` 가 안 보인다.
#    실기로 쟀다(2026-09-24): 그 PATH 로 돌리니 claude·codex 둘 다 「이 기계에 없다」였다.
#    터미널에서 돌릴 때만 되고 **앱으로 띄우면 죽는** 자리라, 검사로는 안 잡히던 병이다.
더볼자리 = (
    "/opt/homebrew/bin",        # Homebrew (애플 실리콘)
    "/usr/local/bin",           # Homebrew (인텔) · 손수 깐 것
    "/opt/local/bin",           # MacPorts
    "~/.local/bin",
    "~/.npm-global/bin", "~/.yarn/bin", "~/.bun/bin", "~/.deno/bin", "~/.volta/bin",
)
# nvm 은 버전마다 폴더가 갈린다 — 있는 것을 다 본다
녹스자리 = "~/.nvm/versions/node/*/bin"


def 길() -> str:
    """CLI 를 찾고 띄울 PATH. **한 군데만 둔다** — 찾는 쪽과 띄우는 쪽이 갈리면 샌다.

    ★★ 찾기만 고치면 안 된다. claude 는 node 로 도는 스크립트라 **띄울 때도** 같은
       PATH 를 줘야 한다 — 안 주면 `env: node: No such file or directory` 로 죽는다.
    ★ 지금 PATH 를 **앞에** 둔다. 터미널에서 돌릴 때는 오너가 고른 것이 이겨야 한다.
    """
    import glob

    자리 = [x for x in (os.environ.get("PATH") or "").split(os.pathsep) if x]
    본것 = set(자리)
    for 곳 in (*더볼자리, *sorted(glob.glob(os.path.expanduser(녹스자리)), reverse=True)):
        곳 = os.path.expanduser(곳)
        if 곳 not in 본것 and os.path.isdir(곳):
            자리.append(곳)
            본것.add(곳)
    return os.pathsep.join(자리)


꼬리최대 = 3000           # stderr 를 되짚을 때 남길 끝자락


def 꼬리(글: str, 최대: int = 꼬리최대) -> str:
    """끝에서부터 남긴다. **탈난 까닭은 끝에 있다.**

    ★★ 앞에서 자르면 머리말만 남고 까닭이 잘려 나간다 — codex 의 stderr 가 딱
       그 꼴이었다(머리말 + 우리가 준 지시가 통째로 앞에 있고 ERROR 는 맨 끝).
    """
    글 = (글 or "").strip()
    if len(글) <= 최대:
        return 글
    잘린 = 글[-최대:]
    # 줄 가운데서 끊지 않는다 — 반 토막 줄은 읽기 나쁘다
    금 = 잘린.find("\n")
    if 0 <= 금 < 200:
        잘린 = 잘린[금 + 1:]
    return "…(앞은 줄였다)\n" + 잘린


def 찾기(실행파일: str) -> str:
    """그 CLI 의 온전한 자리. 없으면 빈 글.

    ★★ **온전한 자리를 써야 한다.** `Popen` 에 `env` 를 줘도 실행파일은 **부모의**
       PATH 로 찾는다(파이썬이 그렇게 돈다) — 그래서 여기서 미리 풀어 준다.
    """
    return shutil.which(실행파일, path=길()) or "" if 실행파일 else ""


class 손:
    """CLI 하나를 어떻게 부르는가. **여기만 고치면 CLI 판올림을 흡수한다.**"""

    이름 = ""
    실행파일 = ""
    # ★ 한 판마다 `돌리기` 가 채워 준다. 마지막 말을 **파일로** 받는 손이 쓴다.
    말자리: Path | None = None
    # ★★ **이어 말하기.** 앞 판의 세션을 주면 그 대화를 **이어서** 한다 — 이것이
    #   없으면 한 마디 할 때마다 처음 보는 사이가 되어 「채팅」이 아니다.
    #   실기로 쟀다(2026-09-24): 「내가 좋아하는 숫자는 47」 뒤에 이어 물으니 47 이라 했다.
    이어서: str = ""
    # ★★ **VC 의 일을 도구로 쥐여 준다.** 이것이 없으면 바깥 AI 는 코드만 고치고
    #   「창고에 적어 둬」 같은 VC 안의 일은 못 한다 — 오너가 「그냥 답만 한다」고
    #   짚은 자리다(2026-09-24). `돌리기` 가 한 판마다 채운다.
    도구자리: Path | None = None

    def 세션찾기(self, 나온것: str, 탈난것: str = "") -> str:
        """이번 판의 세션 이름. 다음 판에 `이어서` 로 돌려주면 대화가 이어진다."""
        return ""

    def 끝난말(self) -> str:
        """손이 `말자리` 에 적어 둔 마지막 말. 안 쓰는 손은 빈 글."""
        자리 = self.말자리
        try:
            return 자리.read_text(encoding="utf-8").strip() if 자리 and 자리.exists() else ""
        except OSError:
            return ""

    def 있나(self) -> bool:
        return bool(찾기(self.실행파일))

    def 명령(self, 지시: str, 읽기전용: bool = False) -> list[str]:
        """이 CLI 를 부르는 명령.

        ★★ `읽기전용` 은 **보는 손**(리뷰)을 위한 것이다. 리뷰가 파일을 고치면
           짓는 손의 일과 섞여 무엇이 누구 탓인지 알 수 없게 된다.
        """
        raise NotImplementedError

    def 읽을말(self, 나온것: str, 탈난것: str = "") -> str:
        """CLI 가 **사람에게 한 말**. 껍데기를 쓴 손은 여기서 벗긴다.

        ★★ 날것(`나온말`)은 자취로 그대로 둔다 — 벗긴 것만 남기면 벗기기가 틀렸을 때
           무엇이 왔는지 알 길이 없다. 그래서 **둘 다 들고 간다.**
        ★★ **stdout 이 비면 stderr 를 본다.** 탈난 까닭을 거기 적는 손이 있다 —
           안 보면 「탈났다」고만 하고 **왜인지는 빈 칸**이 된다(codex 가 실제로 그랬다:
           한도 오류가 통째로 stderr 에 있어 보고가 비었다 · 2026-09-24).
        """
        return (나온것 or "").strip() or 꼬리(탈난것)

    def 끝말(self, 나온것: str, 탈난것: str = "") -> str:
        """마지막 한 줄. 보고에 쓴다 — **성공 판정에는 안 쓴다.**"""
        줄 = [x for x in self.읽을말(나온것, 탈난것).splitlines() if x.strip()]
        return 줄[-1][:500] if 줄 else ""


class 클로드(손):
    """클로드 코드. `-p` 가 한 번 돌리고 끝나는 모습이다.

    ★★ **깃발은 실기로 확정했다**(2026-09-24 · claude 2.1.267):
       - 짓는 손 `--permission-mode acceptEdits` → `x = 1` 을 `x = 2` 로 **실제로 고쳤다**
       - 보는 손 `--permission-mode plan` → 「**반드시 고쳐라**」고 시켜도 계획만 쓰고
         **파일은 그대로였다**(`git status` 비어 있음). 말이 아니라 **판이 막는다.**
       `bypassPermissions` 는 안 쓴다 — 다 열어 두면 막을 수가 없다.
    """

    이름 = "claude"
    실행파일 = "claude"

    def 명령(self, 지시: str, 읽기전용: bool = False) -> list[str]:
        # ★ 이어 말할 때는 `--resume` 을 붙인다. 실기 확인(2026-09-24): 앞 판에서 말한
        #   것을 다음 판이 기억했다. 안 붙이면 매번 처음 보는 사이가 된다.
        이음 = ["--resume", self.이어서] if self.이어서 else []
        # ★★ **MCP 도구는 따로 허락해야 돈다.** 안 열어 주면 「권한 승인이 필요합니다」
        #   하고 아무 일도 안 한다(실기로 그랬다 · 2026-09-24).
        # ★ `--strict-mcp-config` 로 **VC 것만** 쓴다 — 오너가 따로 깔아 둔 MCP 가
        #   섞이면 무엇이 도는지 알 수 없다.
        도구 = ([] if self.도구자리 is None else
              ["--mcp-config", str(self.도구자리), "--strict-mcp-config",
               "--allowed-tools", "mcp__vc"])
        return [self.실행파일, "-p", 지시, "--output-format", "json",
                "--permission-mode", "plan" if 읽기전용 else "acceptEdits", *이음, *도구]

    def 세션찾기(self, 나온것: str, 탈난것: str = "") -> str:
        글 = (나온것 or "").strip()
        if not 글.startswith("{"):
            return ""
        try:
            싼것 = json.loads(글)
        except ValueError:
            return ""
        것 = 싼것.get("session_id") if isinstance(싼것, dict) else None
        return 것.strip() if isinstance(것, str) else ""

    def 읽을말(self, 나온것: str, 탈난것: str = "") -> str:
        """★★ `--output-format json` 은 **껍데기에 싸서** 준다 — 사람 말은 `result` 안에 있다.

        안 벗기면 창고의 검토 자리에 토큰 셈이 적힌 JSON 덩이가 들어앉는다(실기에서
        그렇게 됐다). 벗기다 실패하면 **날것을 그대로** 돌려준다 — 껍데기 모양이
        바뀌어도 말이 사라지지는 않게.
        """
        글 = (나온것 or "").strip()
        if not 글:
            return 꼬리(탈난것)
        if not 글.startswith("{"):
            return 글
        try:
            싼것 = json.loads(글)
        except ValueError:
            return 글
        속 = 싼것.get("result") if isinstance(싼것, dict) else None
        return 속.strip() if isinstance(속, str) and 속.strip() else 글


class 코덱스(손):
    """Codex. `exec` 가 비대화식이고 **기본이 읽기 전용 샌드박스**다.

    ★ 고치게 하려면 `--sandbox workspace-write` 가 필요하다 — 권한을 **필요한 만큼만** 연다.
    ★★ **한도에 걸리면 끝난 코드가 1 이다**(2026-09-24 실기 · codex-cli 0.156.1).
       그래서 「성공을 끝난 코드로 잰다」가 여기서도 맞는다 — 한도 오류를 성공으로 안 읽는다.
    ★★ **codex 는 stdout 에 아무것도 안 쓴다.** 머리말도 답도 탈도 전부 stderr 다
       (실기로 쟀다 · 2026-09-24). 그래서 굽힌 앱으로 협업을 돌렸더니 「탈났다」고만
       하고 **까닭이 빈 칸**이었다. 두 겹으로 막는다:
         1. `-o` 로 **마지막 말만 파일에 받는다**(문서에 있는 깃발이다).
         2. 그 파일이 비면 **stderr 를 그대로** 쓴다 — 지저분해도 까닭은 남는다.
       ★ 성공했을 때 `-o` 가 실제로 무엇을 적는지는 아직 못 쟀다(한도). 그래도
         되짚을 자리가 있으니 **말이 사라지지는 않는다.**
    """

    이름 = "codex"
    실행파일 = "codex"

    def 명령(self, 지시: str, 읽기전용: bool = False) -> list[str]:
        # ★ 기본이 읽기 전용이라 **보는 손일 때는 아무 깃발도 안 준다** — 문서가 그렇다.
        말깃발 = ["-o", str(self.말자리)] if self.말자리 else []
        if self.이어서:
            # ★★ `exec resume` 에는 **`--sandbox` 가 없다**(도움말로 확인). 대신 설정
            #   덮어쓰기가 먹는다 — `--strict-config` 로 걸어 보니 머리말에
            #   `sandbox: workspace-write` 라고 찍혔다(실기 · 2026-09-24).
            판깃발 = [] if 읽기전용 else ["-c", 'sandbox_mode="workspace-write"']
            return [self.실행파일, "exec", "resume", *판깃발, *말깃발,
                    self.이어서, 지시]
        판깃발 = [] if 읽기전용 else ["--sandbox", "workspace-write"]
        return [self.실행파일, "exec", *판깃발, *말깃발, 지시]

    def 세션찾기(self, 나온것: str, 탈난것: str = "") -> str:
        # ★ codex 는 머리말을 **stderr** 에 찍는다 — `session id: <uuid>` 가 거기 있다.
        맞은것 = re.search(r"session id:\s*([0-9A-Fa-f][0-9A-Fa-f-]{7,})",
                        (탈난것 or "") + "\n" + (나온것 or ""))
        return 맞은것.group(1) if 맞은것 else ""

    def 읽을말(self, 나온것: str, 탈난것: str = "") -> str:
        # ★ `-o` 가 적어 준 것이 가장 깨끗하다. 없으면 stdout, 그것도 없으면 stderr.
        return self.끝난말() or (나온것 or "").strip() or 꼬리(탈난것)


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
        읽기전용: bool = False, 이어서: str = "") -> dict:
    """에이전트 CLI 를 프로젝트 폴더에서 돌린다.

    돌려주는 것:
        `{"손", "됐나", "끝난코드", "나온말", "읽을말", "탈말", "끝말", "바뀐파일",
          "원래더럽던것", "차이", "든시간", "세션", "왜"}`

    ★★ `이어서` 에 앞 판의 `세션` 을 주면 **그 대화를 이어서** 한다. 안 주면 매번
       처음 보는 사이가 된다 — 「채팅」이 되려면 이것이 있어야 한다.

    ★ `나온말` 은 **날것**, `읽을말` 은 **껍데기를 벗긴 사람 말**이다. 사람·창고에
      보일 때는 `읽을말`, 자취로 남길 때는 `나온말`.
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
    # ★★ **띄울 때도 같은 길을 준다.** 찾기만 고치면 claude 는 뜨고 그 속의 node 를
    #   못 찾아 죽는다. 그리고 실행파일은 **미리 온전한 자리로 풀어 둔다** — `env` 를
    #   줘도 파이썬은 부모의 PATH 로 찾기 때문이다.
    # ★ 마지막 말을 **파일로** 받는 손을 위한 자리. 프로젝트 **밖**에 둔다 —
    #   안에 두면 git 이 「바뀐 파일」로 세어 누가 뭘 고쳤는지 어지러워진다.
    말집 = tempfile.mkdtemp(prefix="vc-손말-")
    그손.말자리 = Path(말집) / "끝말.txt"
    그손.이어서 = (이어서 or "").strip()
    # ★★ **보는 손에게는 도구를 안 준다.** 읽기만 하라 해 놓고 창고를 고치면
    #   짓는 손의 일과 섞여 누구 탓인지 못 가린다 — 판으로 막는 것과 같은 결이다.
    그손.도구자리 = None
    if not 읽기전용:
        try:
            import vcmcp

            그손.도구자리 = Path(말집) / "vc-도구.json"
            그손.도구자리.write_text(
                json.dumps(vcmcp.설정글(), ensure_ascii=False), encoding="utf-8")
        except Exception:
            그손.도구자리 = None      # 도구를 못 얹어도 일 자체는 돌아야 한다

    명령줄 = list(그손.명령(지시, 읽기전용))
    if 명령줄:
        명령줄[0] = 찾기(명령줄[0]) or 명령줄[0]
    판환경 = {**os.environ, "PATH": 길()}
    try:
        # ★★ **stdin 을 막는다.** codex 는 stdin 이 열려 있으면 「Reading additional
        #   input from stdin…」 하고 기다린다 — 창에는 stdin 이 없으니 굳을 수 있다.
        판 = subprocess.Popen(명령줄, cwd=str(자리), env=판환경,
                            stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    except (OSError, ValueError) as e:
        그손.말자리 = None
        shutil.rmtree(말집, ignore_errors=True)
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
        그손.말자리 = None
        shutil.rmtree(말집, ignore_errors=True)
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
    # ★ 말을 **먼저 꺼내 두고** 치운다 — 지운 뒤에 읽으면 빈 글이 된다
    읽을것, 끝것 = 그손.읽을말(나온말, 탈말), 그손.끝말(나온말, 탈말)
    # ★★ **세션은 실패했어도 챙긴다.** 한도에 걸린 판도 대화 자체는 열려 있어,
    #   버리면 다음 마디가 처음 보는 사이로 돌아간다.
    세션 = 그손.세션찾기(나온말, 탈말) or 그손.이어서
    그손.말자리 = None
    그손.이어서 = ""
    그손.도구자리 = None
    shutil.rmtree(말집, ignore_errors=True)

    return {"손": 그손.이름,
            "됐나": (끝난코드 == 0 and not 끊겼나 and not (읽기전용 and 바뀐)),
            "끝난코드": 끝난코드,
            "나온말": 나온말 or "", "탈말": 탈말 or "",
            "끝말": 끝것, "읽을말": 읽을것,
            "바뀐파일": 바뀐, "원래더럽던것": 원래, "차이": 차,
            "든시간": round(든시간, 1), "끊겼나": 끊겼나, "머리": 전["머리"],
            "읽기전용": 읽기전용, "세션": 세션, "왜": 왜}


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
    # ★★ **VC 의 일을 도구로 쥐여 준다.** 안 주면 코드만 고치고 창고 일은 못 한다.
    #   허락까지 같이 열어야 한다 — 안 열면 「권한 승인이 필요합니다」 하고 멈춘다.
    도구손 = 클로드()
    도구손.도구자리 = Path("/tmp/vc-도구.json")
    명령들 = 도구손.명령("일해라")
    assert "--mcp-config" in 명령들 and "--strict-mcp-config" in 명령들, 명령들
    assert "mcp__vc" in 명령들, 명령들
    assert "--mcp-config" not in 클로드().명령("일해라"), "도구 없이도 깃발이 붙는다"

    # ★★ **실기로 확정한 깃발**(2026-09-24 · claude 2.1.267). 보는 손은 `plan` 이라
    #   「반드시 고쳐라」고 시켜도 파일을 못 고친다 — 말이 아니라 판이 막는다.
    assert 클로드().명령("보기만", 읽기전용=True)[-1] == "plan", 클로드().명령("보기만", True)
    assert 클로드().명령("고쳐라", 읽기전용=False)[-1] == "acceptEdits"
    # 다 열어 두는 판은 안 쓴다 — 열어 두면 막을 수가 없다
    assert "bypassPermissions" not in " ".join(클로드().명령("고쳐라"))
    # ★★ **껍데기를 벗긴다.** `--output-format json` 은 말을 `result` 안에 싼다 —
    #   안 벗기면 창고의 검토 자리에 JSON 덩이가 들어앉는다(실기가 그렇게 됐다).
    싼것 = '{"type":"result","is_error":false,"result":"고칠 데가 없다","total_cost_usd":0.1}'
    assert 클로드().읽을말(싼것) == "고칠 데가 없다", 클로드().읽을말(싼것)
    assert 클로드().끝말(싼것) == "고칠 데가 없다", 클로드().끝말(싼것)
    # 껍데기 모양이 바뀌어도 **말이 사라지면 안 된다** — 못 벗기면 날것 그대로
    assert 클로드().읽을말("그냥 말이다") == "그냥 말이다"
    assert 클로드().읽을말('{"쪼개진 껍데기') == '{"쪼개진 껍데기'
    assert 클로드().읽을말('{"result": 3}') == '{"result": 3}'
    assert 클로드().읽을말("") == ""
    # 딴 손은 안 싸니까 그대로
    assert 코덱스().읽을말(" 다 됐다 \n") == "다 됐다"
    # ★★ **stdout 이 비면 stderr 를 본다.** 안 그러면 「탈났다」고만 하고 까닭이 빈
    #   칸이 된다 — codex 가 실제로 그랬다(모든 말을 stderr 로 낸다 · 2026-09-24).
    assert 코덱스().읽을말("", "ERROR: 한도에 걸렸다") == "ERROR: 한도에 걸렸다"
    # ★★ **되짚을 때는 꼬리를 잡는다** — 탈난 까닭은 끝에 있다. 앞에서 자르면
    #   머리말만 남는다(codex stderr 가 그 꼴이었다: 머리말+지시가 앞, ERROR 가 끝).
    시끄러운 = "머리말\n" * 4000 + "ERROR: 한도에 걸렸다"
    난말 = 코덱스().읽을말("", 시끄러운)
    assert 난말.endswith("ERROR: 한도에 걸렸다"), 난말[-80:]
    assert len(난말) <= 꼬리최대 + 40, len(난말)
    assert 난말.startswith("…(앞은 줄였다)"), 난말[:40]
    assert 꼬리("짧다") == "짧다"
    assert 클로드().읽을말("", "죽었다") == "죽었다"
    assert 손().읽을말("", "까닭") == "까닭"
    assert 코덱스().끝말("", "첫 줄\n마지막 줄") == "마지막 줄"
    # stdout 이 있으면 그것이 이긴다 — stderr 는 되짚을 자리일 뿐
    assert 코덱스().읽을말("한 말", "시끄러운 머리말") == "한 말"

    # ★ codex 는 `-o` 로 **마지막 말만 파일에 받는다**. 그것이 가장 깨끗하다.
    with tempfile.TemporaryDirectory() as _말tmp:
        손말 = 코덱스()
        손말.말자리 = Path(_말tmp) / "끝말.txt"
        assert "-o" in 손말.명령("보기만", 읽기전용=True), 손말.명령("보기만", True)
        assert str(손말.말자리) in 손말.명령("보기만", 읽기전용=True)
        assert 손말.읽을말("", "시끄러운 머리말") == "시끄러운 머리말"   # 아직 안 적혔다
        손말.말자리.write_text("  판정: 좋다  \n", encoding="utf-8")
        assert 손말.읽을말("stdout 것", "stderr 것") == "판정: 좋다", 손말.읽을말("a", "b")
    # 말자리가 없으면 깃발도 없다 — 없는 파일을 가리키면 codex 가 탈난다
    assert "-o" not in 코덱스().명령("보기만", 읽기전용=True)

    # ★★ **이어 말하기.** 앞 판의 세션을 주면 그 대화를 이어서 한다 — 실기로 쟀다
    #   (2026-09-24): 「좋아하는 숫자는 47」 뒤에 이어 물으니 47 이라 답했다.
    이은클 = 클로드()
    이은클.이어서 = "SESS-1"
    assert "--resume" in 이은클.명령("또"), 이은클.명령("또")
    assert 이은클.명령("또")[-1] == "SESS-1"
    assert "--resume" not in 클로드().명령("처음")     # 처음엔 안 붙인다
    assert 클로드().세션찾기('{"session_id":"S9","result":"ok"}') == "S9"
    assert 클로드().세션찾기("그냥 말") == "" and 클로드().세션찾기("") == ""
    # codex 는 머리말을 stderr 에 찍는다 — 거기서 세션을 줍는다(실기로 본 그 줄이다)
    assert 코덱스().세션찾기("", "session id: 01a0cf74-bd65-78c1-85ec-591273451563") \
        == "01a0cf74-bd65-78c1-85ec-591273451563"
    assert 코덱스().세션찾기("", "아무 말") == ""
    이은코 = 코덱스()
    이은코.이어서 = "ID9"
    # ★ `exec resume` 에는 `--sandbox` 가 없다(도움말) — 설정 덮어쓰기로 연다.
    #   `--strict-config` 로 걸어 보니 머리말에 `sandbox: workspace-write` 라 찍혔다.
    assert 이은코.명령("고쳐라")[:3] == ["codex", "exec", "resume"], 이은코.명령("고쳐라")
    assert 'sandbox_mode="workspace-write"' in 이은코.명령("고쳐라")
    assert "--sandbox" not in 이은코.명령("고쳐라"), "resume 에 없는 깃발을 준다"
    assert 이은코.명령("고쳐라")[-2:] == ["ID9", "고쳐라"]
    assert 'sandbox_mode="workspace-write"' not in 이은코.명령("보기만", 읽기전용=True)

    # ★ Codex 는 권한을 **필요한 만큼만** 연다
    assert "--sandbox" in 코덱스().명령("일해라"), 코덱스().명령("일해라")
    assert "workspace-write" in 코덱스().명령("일해라")

    # ★★ **굽힌 앱의 PATH 로도 찾아야 한다.** Finder 로 띄운 `.app` 은 셸 PATH 를
    #   못 받는다 — 터미널에서만 되고 앱으로 띄우면 죽던 자리다(실기 · 2026-09-24).
    with tempfile.TemporaryDirectory() as _길tmp:
        가짜빈 = Path(_길tmp) / "bin"
        가짜빈.mkdir()
        놈 = 가짜빈 / "vc-시험-클리"
        놈.write_text("#!/bin/sh\necho '{\"result\":\"길 시험\"}'\n", encoding="utf-8")
        놈.chmod(0o755)

        class _길손(손):
            이름, 실행파일 = "길시험", "vc-시험-클리"

            def 명령(self, 지시, 읽기전용=False):
                return [self.실행파일]

            def 읽을말(self, 나온것, 탈난것=""):
                return 클로드().읽을말(나온것, 탈난것)

        옛길, 옛자리 = os.environ.get("PATH", ""), 더볼자리
        globals()["더볼자리"] = (*옛자리, str(가짜빈))
        try:
            # launchd 가 주는 그 PATH — 여기엔 브루도 ~/.local/bin 도 없다
            os.environ["PATH"] = "/usr/bin:/bin:/usr/sbin:/sbin"
            assert _길손().있나(), "굽힌 앱의 PATH 에서 CLI 를 못 찾는다"
            assert str(가짜빈) in 길(), 길()
            assert 찾기("vc-시험-클리") == str(놈), 찾기("vc-시험-클리")
            assert 찾기("vc-없는것-zzz") == "" and 찾기("") == ""

            뿌리길 = Path(_길tmp) / "projects"
            (뿌리길 / "PathApp").mkdir(parents=True)
            난것 = 돌리기("PathApp", "돌아라", 뿌리=뿌리길, 손물건=_길손())
            # ★ 찾기만 고치면 안 된다 — **띄우기까지** 같은 길로 돼야 한다
            assert 난것["됐나"], 난것
            assert 난것["읽을말"] == "길 시험", 난것["읽을말"]
        finally:
            os.environ["PATH"] = 옛길
            globals()["더볼자리"] = 옛자리
        # 되돌린 뒤엔 다시 안 보인다 — 검사가 딴 검사에 새지 않는다
        assert not _길손().있나()

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
        assert 난것["읽을말"] == 난것["나온말"].strip()   # 안 싸는 손은 그대로

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

        # ★★ **세션은 실패했어도 챙긴다** — 버리면 다음 마디가 처음 보는 사이가 된다
        class _세션손(손):
            이름, 실행파일 = "세션", "python3"

            def 있나(self):
                return True

            def 명령(self, 지시, 읽기전용=False):
                import sys as _s
                return [_s.executable, "-c",
                        "import sys; sys.stderr.write('session id: 01a0cf74-bd65-78c1-85ec-591273451563'); sys.exit(1)"]

            def 세션찾기(self, 나온것, 탈난것=""):
                return 코덱스().세션찾기(나온것, 탈난것)

        난것 = 돌리기("CliApp", "일해라", 뿌리=뿌리, 손물건=_세션손())
        assert not 난것["됐나"] and 난것["세션"] == "01a0cf74-bd65-78c1-85ec-591273451563", 난것
        # 손물건은 다시 쓰이니 **판이 끝나면 비워 둔다** — 안 비우면 딴 대화로 샌다
        손비움 = 코덱스()
        돌리기("CliApp", "일해라", 뿌리=뿌리, 손물건=손비움, 이어서="ZZZ")
        assert 손비움.이어서 == "", 손비움.이어서

        # ★★ **탈난 까닭이 빈 칸이면 안 된다.** stderr 로만 말하는 손이 있다.
        class _탈만말하는손(손):
            이름, 실행파일 = "탈만", "python3"

            def 있나(self):
                return True

            def 명령(self, 지시, 읽기전용=False):
                import sys as _s
                return [_s.executable, "-c",
                        "import sys; sys.stderr.write('ERROR: 한도에 걸렸다'); sys.exit(1)"]

        난것 = 돌리기("CliApp", "일해라", 뿌리=뿌리, 손물건=_탈만말하는손())
        assert not 난것["됐나"], 난것
        assert 난것["읽을말"] == "ERROR: 한도에 걸렸다", 난것["읽을말"]
        assert "한도" in 사람말(난것), 사람말(난것)

        # ★★ **stdin 을 막는다.** 열어 두면 stdin 을 기다리는 손이 영영 안 끝난다
        #   (codex 가 「Reading additional input from stdin…」 하고 선다).
        class _stdin기다리는손(손):
            이름, 실행파일 = "기다림", "python3"

            def 있나(self):
                return True

            def 명령(self, 지시, 읽기전용=False):
                import sys as _s
                return [_s.executable, "-c",
                        "import sys; print(len(sys.stdin.read()))"]

        t0 = time.perf_counter()
        난것 = 돌리기("CliApp", "일해라", 뿌리=뿌리, 제한초=8, 손물건=_stdin기다리는손())
        assert not 난것["끊겼나"], "stdin 이 열려 있어 손이 기다렸다"
        assert 난것["읽을말"] == "0", 난것["읽을말"]
        assert time.perf_counter() - t0 < 8, "stdin 을 기다리느라 늦었다"

        # ★ 말집은 **프로젝트 밖**이라 바뀐 파일로 안 세어진다. 그리고 치워진다.
        손치움 = 코덱스()
        난것 = 돌리기("CliApp", "일해라", 뿌리=뿌리, 손물건=가짜())
        assert 난것["바뀐파일"] == [], 난것["바뀐파일"]
        assert 손치움.말자리 is None

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

        # ★★ **보는 손에게는 도구를 안 준다** — 읽기만 하라 해 놓고 창고를 고치면 안 된다
        도구잼 = 클로드()
        돌리기("CliApp", "보기만", 뿌리=뿌리, 읽기전용=True, 손물건=도구잼)
        assert 도구잼.도구자리 is None, 도구잼.도구자리
        본것 = {}

        class _도구본손(가짜):
            def 명령(self, 지시, 읽기전용=False):
                # ★ **그 자리에서** 본다 — 판이 끝나면 말집째 치워져 나중엔 없다
                본것["자리"] = self.도구자리
                본것["있나"] = bool(self.도구자리 and self.도구자리.exists())
                본것["글"] = (self.도구자리.read_text(encoding="utf-8")
                           if 본것["있나"] else "")
                return super().명령(지시, 읽기전용)

        돌리기("CliApp", "고쳐라", 뿌리=뿌리, 손물건=_도구본손())
        assert 본것.get("있나"), 본것
        assert '"mcpServers"' in 본것["글"] and '"vc"' in 본것["글"], 본것["글"][:200]
        # ★ 도구 설정은 **프로젝트 밖**에 둔다 — 안에 두면 바뀐 파일로 세어진다
        assert str(자리) not in str(본것["자리"]), 본것["자리"]

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
