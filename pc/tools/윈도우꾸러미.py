"""윈도우 PC 로 가져갈 **소스만** 묶는다.

★★ **`zip` 명령으로 묶으면 한글 이름이 윈도우에서 깨진다.** 이름을 UTF-8 로 넣으면서
   그렇다는 깃발(0x800)을 안 세워서, 윈도우가 옛 완성형으로 읽는다 — 소스에 한글
   이름이 534개라 통째로 뭉개졌다(실기로 잡았다 · 2026-09-24).
   파이썬 `zipfile` 은 ASCII 가 아닌 이름에 그 깃발을 스스로 세운다.

★ 맥 전용(venv·dist)·모델·db 는 안 넣는다. 기계마다 다르고 무겁다 —
  4MB 면 무엇으로든 옮긴다.
"""
from __future__ import annotations

import sys
import zipfile
from pathlib import Path

뺄폴더 = {".venv-mac", "dist", "build", "__pycache__", "$받을자리", "vc-잠금",
        ".git", ".pytest_cache", "node_modules"}
뺄끝 = (".db", ".db-shm", ".db-wal", ".pyc", ".pyo", ".DS_Store", ".log")


def 넣을까(쪽: Path, 뿌리: Path) -> bool:
    if any(칸 in 뺄폴더 for 칸 in 쪽.relative_to(뿌리).parts[:-1]):
        return False
    if 쪽.name in 뺄폴더 or 쪽.name.endswith(뺄끝):
        return False
    return 쪽.is_file() and not 쪽.is_symlink()


def 묶기(뿌리: Path, 낼곳: Path) -> tuple[int, int]:
    낼곳.parent.mkdir(parents=True, exist_ok=True)
    몇, 바이트 = 0, 0
    with zipfile.ZipFile(낼곳, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for 쪽 in sorted(뿌리.rglob("*")):
            if not 넣을까(쪽, 뿌리):
                continue
            z.write(쪽, Path("pc") / 쪽.relative_to(뿌리))
            몇 += 1
            바이트 += 쪽.stat().st_size
    return 몇, 바이트


def _self_check() -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        뿌리 = Path(tmp) / "pc"
        (뿌리 / "tools").mkdir(parents=True)
        (뿌리 / "eb.py").write_text("x = 1\n", encoding="utf-8")
        (뿌리 / "한글 이름.md").write_text("한글\n", encoding="utf-8")
        (뿌리 / "tools" / "make_icon.py").write_text("y = 2\n", encoding="utf-8")
        for 뺄것 in ("dist", "__pycache__", ".venv-mac", "$받을자리"):
            (뿌리 / 뺄것).mkdir()
            (뿌리 / 뺄것 / "큰것.bin").write_text("x" * 100, encoding="utf-8")
        (뿌리 / "notes_index.db").write_text("db", encoding="utf-8")

        낼곳 = Path(tmp) / "꾸러미.zip"
        몇, _ = 묶기(뿌리, 낼곳)
        with zipfile.ZipFile(낼곳) as z:
            이름들 = z.namelist()
            # ★★ **한글 이름에 UTF-8 깃발이 서야 윈도우에서 안 깨진다** — 이것이 이 파일의 까닭이다
            한글것 = [i for i in z.infolist() if not i.filename.isascii()]
            assert 한글것, 이름들
            assert all(i.flag_bits & 0x800 for i in 한글것), "UTF-8 깃발이 없다 — 윈도우에서 깨진다"
            assert "pc/한글 이름.md" in 이름들, 이름들
        assert "pc/eb.py" in 이름들 and "pc/tools/make_icon.py" in 이름들, 이름들
        # 맥 전용·모델·db 는 안 들어간다 — 기계마다 다르고 무겁다
        for 없어야 in ("dist", "__pycache__", ".venv-mac", "$받을자리"):
            assert not any(f"/{없어야}/" in n for n in 이름들), (없어야, 이름들)
        assert not any(n.endswith(".db") for n in 이름들), 이름들
        assert 몇 == 3, 이름들
    print("윈도우꾸러미 self-check 통과")


if __name__ == "__main__":
    if "--check" in sys.argv:
        _self_check()
    else:
        뿌리 = Path(__file__).resolve().parent.parent
        낼곳 = Path(sys.argv[1]) if len(sys.argv) > 1 else (
            Path.home() / "projects" / "_빌드파일" / "VC-소스-윈도우용.zip")
        몇, 바이트 = 묶기(뿌리, 낼곳)
        print(f"{낼곳}  파일 {몇}개 · 원본 {바이트/1048576:.1f}MB "
              f"· 묶은 뒤 {낼곳.stat().st_size/1048576:.1f}MB")
