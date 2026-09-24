"""코드 파일 — 헤르메스의 IDE 조각 하나. 프로젝트 파일을 **보고·읽고·쓴다.**

관제탑이 선 뒤에 얹는 첫 IDE 조각이다(오너 2026-09-21: 「파일 나무 + 편집기」부터).
화면은 안 쓴다 — 여기는 규칙과 안전만 맡고, 창과 서버가 그 위에 붙는다.

★★ **제일 중요한 것은 자리를 벗어나지 않는 것이다.** 상대 경로를 그대로 이어 붙이면
   `../../.ssh/id_rsa` 한 줄로 창고 밖 아무 파일이나 읽고 쓸 수 있다. 이어 붙인 뒤
   **풀어서(resolve) 프로젝트 안인지 다시 본다** — 심볼릭 링크도 그때 걸린다.

★★ **큰 파일·이진 파일은 안 연다.** 편집기에 넣으면 창이 굳고, 이진을 글자로 읽어
   저장하면 **파일이 망가진다.** 열지 않는 편이 낫다.

★ **지난 판은 git 이 맡는다.** 창고 글과 달리 코드에는 이미 판 관리가 있다 —
  여기서 또 만들면 두 군데가 된다. 그래서 `차리기` 가 `git init` 을 먼저 한다.
"""

from __future__ import annotations

from pathlib import Path

import hermes

최대크기 = 2_000_000          # 2MB. 넘으면 안 연다 — 편집기에 넣으면 창이 굳는다
나무최대 = 500                # 한 번에 보여 줄 파일 수. 더 있으면 잘렸다고 알린다

# 들여다볼 값이 없는 자리. 여는 쪽이 아니라 **세는 쪽**에서 뺀다 — 목록이 쓰레기로 덮인다.
안볼폴더 = frozenset({
    ".git", ".hg", ".svn", "node_modules", "__pycache__", ".pytest_cache",
    ".mypy_cache", ".ruff_cache", "dist", "build", ".idea", ".vscode",
    ".history", ".이력", ".DS_Store",
})
안볼꼬리 = (".pyc", ".pyo", ".so", ".dylib", ".dll", ".exe", ".bin", ".gguf",
          ".onnx", ".zip", ".gz", ".tar", ".7z", ".png", ".jpg", ".jpeg",
          ".gif", ".webp", ".heic", ".mp4", ".mov", ".mp3", ".wav", ".pdf",
          ".db", ".sqlite", ".sqlite3", ".db-shm", ".db-wal", ".db-journal")


def _가상폴더인가(이름: str) -> bool:
    return 이름 in 안볼폴더 or (이름.startswith(".venv") or 이름.endswith(".egg-info"))


def 프로젝트뿌리(이름: str, 뿌리: Path | None = None) -> Path:
    return (Path(뿌리) if 뿌리 else hermes.기본뿌리) / 이름


def 프로젝트들(뿌리: Path | None = None) -> list[str]:
    """이 기계에 차려진 프로젝트 이름들. **영문 이름만** 센다(차리기가 그렇게 만든다)."""
    곳 = Path(뿌리) if 뿌리 else hermes.기본뿌리
    if not 곳.is_dir():
        return []
    낸다 = []
    for p in sorted(곳.iterdir()):
        try:
            if p.is_dir() and hermes.영문이름인가(p.name):
                낸다.append(p.name)
        except OSError:
            continue
    return 낸다


def 안전한자리(이름: str, 상대: str, 뿌리: Path | None = None) -> Path | None:
    """프로젝트 **안**의 자리면 그 자리, 아니면 None.

    ★★ 이어 붙인 뒤 **풀어서** 다시 본다. `..` 도 심볼릭 링크도 여기서 걸린다 —
       안 걸면 `../../.ssh/id_rsa` 한 줄로 창고 밖이 통째로 열린다.
    """
    if not hermes.영문이름인가(이름):
        return None
    상대 = (상대 or "").strip()
    # ★★ **절대 경로는 거절한다.** 앞 빗금만 떼어 받으면 `/etc/passwd` 가 조용히
    #   `<프로젝트>/etc/passwd` 가 된다 — 막은 것도 아니고 물은 것도 아닌 꼴이다.
    if not 상대 or 상대.startswith(("/", "\\")) or (len(상대) > 1 and 상대[1] == ":"):
        return None
    바닥 = 프로젝트뿌리(이름, 뿌리)
    try:
        바닥풀린 = 바닥.resolve()
        자리 = (바닥 / 상대).resolve()
        자리.relative_to(바닥풀린)
    except (OSError, ValueError):
        return None
    if any(_가상폴더인가(조각) for 조각 in 자리.parts):
        return None
    return 자리


def _git이아는것(바닥: Path) -> list[str] | None:
    """git 이 **따라가는** 파일들. git 이 없거나 저장소가 아니면 None.

    ★★ **`.gitignore` 를 우리가 다시 해석하지 않는다.** 직접 훑었더니 VC 에서만 500개가
       넘어 잘렸고 `eb.db-wal` 같은 것이 목록을 덮었다 — 무엇이 코드인지는 **이미 git 이
       안다.** 규칙을 두 군데 적으면 갈린다(오늘만 세 번 밟았다).
    """
    import subprocess

    try:
        # ★★ **아직 `add` 안 한 파일도 센다**(`--others`). `ls-files` 만 쓰면 방금 만든
        #   파일이 VC 에 **안 보인다** — 차리고 첫 파일을 쓰는 순간 목록이 비었다
        #   (2026-09-21 배선 검사가 잡았다). `--exclude-standard` 라 `.gitignore` 는 그대로 듣는다.
        난것 = subprocess.run(
            ["git", "-C", str(바닥), "ls-files", "-z",
             "--cached", "--others", "--exclude-standard"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    if 난것.returncode != 0:
        return None
    return [x for x in (난것.stdout or "").split("\0") if x]


def 나무(이름: str, 뿌리: Path | None = None, 최대: int = 나무최대) -> dict:
    """프로젝트 안의 파일 목록(상대 경로). `{"파일": [...], "잘림": bool, "왜": ...}`.

    git 저장소면 **git 이 아는 것**만, 아니면 직접 훑는다.
    """
    바닥 = 프로젝트뿌리(이름, 뿌리)
    if not hermes.영문이름인가(이름) or not 바닥.is_dir():
        return {"파일": [], "잘림": False, "왜": "그런 프로젝트가 없다"}

    git것 = _git이아는것(바닥)
    if git것 is not None:
        쓸것 = []
        for 상대 in git것:
            if any(_가상폴더인가(조각) for 조각 in Path(상대).parts):
                continue
            if 상대.lower().endswith(안볼꼬리):
                continue
            자리 = 바닥 / 상대
            try:
                if not 자리.is_file() or 자리.is_symlink() or 자리.stat().st_size > 최대크기:
                    continue
            except OSError:
                continue
            쓸것.append(상대)
        쓸것.sort()
        return {"파일": 쓸것[:최대], "잘림": len(쓸것) > 최대, "왜": ""}

    낸다: list[str] = []
    잘림 = False
    쌓기 = [바닥]
    while 쌓기:
        곳 = 쌓기.pop()
        try:
            것들 = sorted(곳.iterdir())
        except OSError:
            continue
        for p in 것들:
            if _가상폴더인가(p.name):
                continue
            try:
                if p.is_symlink():
                    continue          # 링크는 안 따라간다 — 자리를 벗어난다
                if p.is_dir():
                    쌓기.append(p)
                    continue
                if p.name.lower().endswith(안볼꼬리):
                    continue
                if p.stat().st_size > 최대크기:
                    continue
            except OSError:
                continue
            if len(낸다) >= 최대:
                잘림 = True
                break
            낸다.append(p.relative_to(바닥).as_posix())
        if 잘림:
            break
    return {"파일": sorted(낸다), "잘림": 잘림, "왜": ""}


def 글인가(자리: Path) -> bool:
    """글자 파일인가. **첫 조각에 0 바이트가 있으면 이진**으로 본다(흔한 어림)."""
    try:
        조각 = 자리.open("rb").read(4096)
    except OSError:
        return False
    if b"\x00" in 조각:
        return False
    try:
        조각.decode("utf-8")
    except UnicodeDecodeError:
        return True          # 잘린 글자일 수 있다 — 읽을 때 다시 본다
    return True


def 읽기(이름: str, 상대: str, 뿌리: Path | None = None) -> dict:
    """파일 한 장. `{"글", "줄수", "왜"}`."""
    자리 = 안전한자리(이름, 상대, 뿌리)
    if 자리 is None:
        return {"글": "", "줄수": 0, "왜": "그 자리는 못 연다"}
    if not 자리.is_file():
        return {"글": "", "줄수": 0, "왜": "그런 파일이 없다"}
    try:
        크기 = 자리.stat().st_size
    except OSError as e:
        return {"글": "", "줄수": 0, "왜": f"못 읽었다: {type(e).__name__}"}
    if 크기 > 최대크기:
        return {"글": "", "줄수": 0, "왜": f"너무 크다({크기 // 1024}KB) — 편집기에 넣으면 창이 굳는다"}
    if not 글인가(자리):
        return {"글": "", "줄수": 0, "왜": "이진 파일이다 — 글자로 열면 저장할 때 망가진다"}
    try:
        글 = 자리.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return {"글": "", "줄수": 0, "왜": f"못 읽었다: {type(e).__name__}"}
    return {"글": 글, "줄수": 글.count("\n") + 1, "왜": ""}


def 쓰기(이름: str, 상대: str, 글: str, 뿌리: Path | None = None) -> dict:
    """파일 한 장을 쓴다. 없으면 만든다. `{"됐나", "왜"}`.

    ★ **이진 파일은 안 덮는다.** 글자로 열지도 못하는 것을 글자로 쓰면 망가진다.
    ★ 지난 판은 **git 이 맡는다** — 창고 글과 달리 코드에는 이미 판 관리가 있다.
    """
    자리 = 안전한자리(이름, 상대, 뿌리)
    if 자리 is None:
        return {"됐나": False, "왜": "그 자리는 못 쓴다"}
    if not isinstance(글, str):
        return {"됐나": False, "왜": "글자가 아니다"}
    if len(글.encode("utf-8")) > 최대크기:
        return {"됐나": False, "왜": "너무 크다"}
    if 자리.exists() and not 글인가(자리):
        return {"됐나": False, "왜": "이진 파일이다 — 덮으면 망가진다"}
    try:
        자리.parent.mkdir(parents=True, exist_ok=True)
        잠깐 = 자리.with_name(자리.name + ".vc-tmp")
        잠깐.write_text(글, encoding="utf-8")
        잠깐.replace(자리)          # 반쯤 쓰다 죽어도 옛 파일이 남는다
    except OSError as e:
        return {"됐나": False, "왜": f"못 썼다: {type(e).__name__}"}
    return {"됐나": True, "왜": ""}


def _self_check() -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        뿌리 = Path(tmp) / "projects"
        바닥 = 뿌리 / "DemoApp"
        (바닥 / "src").mkdir(parents=True)
        (바닥 / "CLAUDE.md").write_text("# DemoApp\n", encoding="utf-8")
        (바닥 / "src" / "main.py").write_text("print('안녕')\n", encoding="utf-8")
        (바닥 / ".git").mkdir()
        (바닥 / ".git" / "config").write_text("비밀\n", encoding="utf-8")
        (바닥 / "__pycache__").mkdir()
        (바닥 / "__pycache__" / "x.pyc").write_bytes(b"\x00\x01")
        (바닥 / "그림.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 50)
        (뿌리 / "한글프로젝트").mkdir()

        assert 프로젝트들(뿌리) == ["DemoApp"], 프로젝트들(뿌리)   # 한글 이름은 안 센다

        난것 = 나무("DemoApp", 뿌리)
        assert 난것["파일"] == ["CLAUDE.md", "src/main.py"], 난것["파일"]
        assert not 난것["잘림"]

        # ★★ **자리를 벗어나면 못 연다** — 안 막으면 창고 밖이 통째로 열린다
        for 나쁨 in ("../../비밀.txt", "/etc/passwd", "src/../../밖.txt", "", "   "):
            assert 안전한자리("DemoApp", 나쁨, 뿌리) is None, 나쁨
        assert 안전한자리("DemoApp", "src/main.py", 뿌리) is not None
        # 안 볼 폴더도 못 연다
        assert 안전한자리("DemoApp", ".git/config", 뿌리) is None
        # 한글 프로젝트 이름은 아예 안 받는다
        assert 안전한자리("한글프로젝트", "a.txt", 뿌리) is None

        # 심볼릭 링크로 빠져나가는 것도 막는다
        밖 = Path(tmp) / "밖.txt"
        밖.write_text("밖의 것\n", encoding="utf-8")
        try:
            (바닥 / "샛길").symlink_to(밖)
        except OSError:
            pass
        else:
            assert 안전한자리("DemoApp", "샛길", 뿌리) is None, "심볼릭 링크로 빠져나간다"
            assert "샛길" not in 나무("DemoApp", 뿌리)["파일"]

        # --- 읽기 ---
        난것 = 읽기("DemoApp", "src/main.py", 뿌리)
        assert 난것["글"] == "print('안녕')\n" and 난것["줄수"] == 2, 난것
        assert 읽기("DemoApp", "없는파일.py", 뿌리)["왜"] == "그런 파일이 없다"
        assert "못 연다" in 읽기("DemoApp", "../밖.txt", 뿌리)["왜"]
        # ★ 이진 파일은 안 연다 — 글자로 열면 저장할 때 망가진다
        assert "이진" in 읽기("DemoApp", "그림.png", 뿌리)["왜"], 읽기("DemoApp", "그림.png", 뿌리)
        # ★ 큰 파일도 안 연다
        (바닥 / "큰것.txt").write_text("가" * (최대크기 // 2), encoding="utf-8")
        assert "너무 크다" in 읽기("DemoApp", "큰것.txt", 뿌리)["왜"]

        # --- 쓰기 ---
        assert 쓰기("DemoApp", "src/main.py", "print('바꿈')\n", 뿌리)["됐나"]
        assert (바닥 / "src" / "main.py").read_text(encoding="utf-8") == "print('바꿈')\n"
        # 없던 파일도 만든다(프로젝트 안이면)
        assert 쓰기("DemoApp", "src/새것/hello.py", "x = 1\n", 뿌리)["됐나"]
        assert (바닥 / "src" / "새것" / "hello.py").exists()
        # ★★ 밖으로는 못 쓴다
        assert not 쓰기("DemoApp", "../../밖.txt", "망가뜨리기\n", 뿌리)["됐나"]
        assert 밖.read_text(encoding="utf-8") == "밖의 것\n", "자리 밖 파일을 덮었다"
        # ★ 이진은 안 덮는다
        assert not 쓰기("DemoApp", "그림.png", "글자\n", 뿌리)["됐나"]
        assert (바닥 / "그림.png").read_bytes().startswith(b"\x89PNG")
        # 쓰다 만 임시 파일이 남지 않는다
        assert not list(바닥.rglob("*.vc-tmp")), list(바닥.rglob("*.vc-tmp"))

        # 목록이 잘리면 잘렸다고 말한다 — 말없이 자르면 사람이 없는 줄 안다
        for i in range(12):
            (바닥 / f"f{i}.txt").write_text("x", encoding="utf-8")
        짧게 = 나무("DemoApp", 뿌리, 최대=5)
        assert 짧게["잘림"] and len(짧게["파일"]) == 5, 짧게

        assert 나무("없는프로젝트", 뿌리)["왜"] == "그런 프로젝트가 없다"

        # ★★ **git 이 있으면 git 이 아는 것만 센다.** `.gitignore` 를 우리가 다시 해석하면
        #   규칙이 두 군데가 된다 — 직접 훑었더니 VC 에서 500개로 잘리고 `eb.db-wal` 이
        #   목록을 덮었다(2026-09-21 창을 띄워 보고 알았다).
        import subprocess as _깃

        깃있나 = _깃.run(["git", "-C", str(바닥), "init", "-q"],
                      capture_output=True).returncode == 0
        if 깃있나:
            (바닥 / ".gitignore").write_text("무시할것/\n", encoding="utf-8")
            (바닥 / "무시할것").mkdir(exist_ok=True)
            (바닥 / "무시할것" / "쓰레기.txt").write_text("x", encoding="utf-8")
            _깃.run(["git", "-C", str(바닥), "add", "-A"], capture_output=True)
            난것깃 = 나무("DemoApp", 뿌리)
            assert "src/main.py" in 난것깃["파일"], 난것깃["파일"][:8]
            assert not any(f.startswith("무시할것") for f in 난것깃["파일"]), \
                f"git 이 무시하는 것을 센다: {난것깃['파일']}"
            assert "그림.png" not in 난것깃["파일"], "이진 파일을 센다"
            # ★★ **아직 `add` 안 한 파일도 보인다** — 안 보이면 방금 만든 파일을 못 고친다
            (바닥 / "갓만든것.py").write_text("y = 2\n", encoding="utf-8")
            assert "갓만든것.py" in 나무("DemoApp", 뿌리)["파일"], \
                나무("DemoApp", 뿌리)["파일"][:8]

    print("codefiles self-check 통과")


if __name__ == "__main__":
    import sys

    if "--check" in sys.argv:
        _self_check()
