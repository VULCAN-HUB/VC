"""볼트 들이기 — 남의 폴더를 **글 하나 = 글 하나**로 들인다. 화면도 모델도 안 쓴다.

`ingest.py` 와 헷갈리면 안 된다. 거기는 **남의 파일 더미에서 쓸 것만 건져 오는** 길이라
문서를 표제마다 도막으로 쪼갠다. 옵시디언 볼트에 그걸 대 보니 이렇게 됐다(실측):

    119장 중 **110장이 여러 도막으로 쪼개지고**(한 문서가 최대 19도막),
    **프런트매터는 0장 살아남고**(`type` 94장이 통째로 날아간다),
    문지기가 도막 69개를 버렸다.

링크 글자는 남아도 가리킬 대상이 흩어져 **링크 802개가 갈 곳을 잃는다.** 볼트는 건져 올
더미가 아니라 **이미 정리된 창고**다. 그래서 쪼개지 않고, 버리지 않고, 있는 그대로 들인다.

들이는 규칙은 볼트를 재서 정했다(오너 2026-09-20):

- **제목은 본문 첫 `# 표제`** — 볼트의 파일 이름은 `2026-08-05-ar-ai-...` 같은 기계 이름이고
  진짜 제목은 본문에 있었다(119장 전부 있고 **겹치는 것이 없었다**).
- **파일 이름은 별칭으로** — `[[링크]]` 는 파일 이름을 가리킨다. 별칭에 넣어 두면
  VC 가 별칭으로 글을 찾으므로 **링크 762개가 그대로 이어진다**(끊긴 40개는 원래 끊겨 있었다).
- **`type` 은 갈래로** — 볼트의 `type` 과 폴더가 1:1이었다(`wiki/errors` ↔ `error`).
  폴더 뜻이 갈래에 다 담기므로 폴더를 따로 살릴 것이 없다.
- **`date` 로 자리를 잡는다** — VC 의 연/월 규칙에 그대로 흩어진다.
- **모르는 앞머리는 그대로 지고 간다** — `Note.extra` 가 이미 그 일을 한다.
- **들인 곳을 적어 둔다** — 잘못 들였을 때 **한꺼번에 뺄 수 있어야** 한다.
"""

from __future__ import annotations

import re
import time
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

import ingest
import wiki
from notes import Note, Notes, parse_links, 제목맞춤

# 들인 글에 적어 두는 열쇠. 한글이라 볼트의 `source`·`type` 과 부딪히지 않는다.
온곳열쇠 = "들인곳"

#  ★★ **폴더가 갈래를 말해 준다.** 옵시디언 볼트는 폴더로 종류를 갈라 두는 것이 흔하고
#  (오너 볼트가 그랬다: `wiki/errors`·`wiki/decisions`…), `type` 앞머리보다 **더 믿을 만하다** —
#  날짜가 없어 `type` 이 빠진 글도 폴더는 제 자리에 있었다(실측: 「검사가 다 통과해도 구운
#  것으로는 안 돌 수 있다」가 `type` 없이 `wiki/guidelines` 에 있었다).
#  새 기준(`wiki.갈래들`)으로 **옮겨** 담는다 — 옛 이름을 그대로 두면 기준이 둘이 된다.
폴더갈래 = {
    "dev-tasks": "작업", "dev-task": "작업",
    "errors": "오류", "error": "오류",
    "decisions": "결정", "decision": "결정",
    "projects": "엔티티", "project": "엔티티",
    "guidelines": "규칙", "guideline": "규칙",
    "design": "설계", "sources": "출처요약", "source": "출처요약",
    "concepts": "개념", "concept": "개념",
    "conversations": "메모",
}

#  창고를 **돌리던 틀**이 사는 자리. 새 창고에는 이미 제 스키마·지도·일지가 있으므로
#  이것들이 기준 노릇을 하면 안 된다 — 버리지는 않고 `상태: 끝남` 으로 내려 둔다.
#  (오너 2026-09-21: 「현재 구현한 창고의 기준이 메인이다」)
틀폴더 = ("", "prompts", "scripts", "templates")

#  남의 `status` 를 우리 `상태` 로. **원래 값은 지우지 않는다**(`status` 로도 찾을 수 있다).
상태옮김 = {
    "active": "살아있음", "open": "살아있음", "wip": "살아있음",
    "draft": "보류", "planning": "보류", "todo": "보류", "paused": "보류",
    "resolved": "끝남", "done": "끝남", "closed": "끝남", "design-complete": "끝남",
    "superseded": "버림", "archived": "버림", "dropped": "버림",
}

_표제 = re.compile(r"^#[ \t]+(.+?)[ \t]*$", re.M)
_앞날짜 = re.compile(r"^(\d{4})-(\d{2})-(\d{2})")
_날짜꼴 = re.compile(r"^(\d{4})-(\d{2})(?:-(\d{2}))?")
_앞머리 = re.compile(r"^---\r?\n", re.M)


@dataclass
class 들일것:
    """파일 하나에서 읽어 낸, 창고에 넣을 글 하나."""

    제목: str
    몸: str
    갈래: str
    날짜: str                    # ISO. 창고가 이걸로 연/월 자리를 잡는다
    별칭: list[str] = field(default_factory=list)
    남의것: dict = field(default_factory=dict)
    온곳: str = ""               # 「볼트이름/상대경로」

    def 글로(self) -> Note:
        남의것 = dict(self.남의것)
        남의것[온곳열쇠] = self.온곳
        return Note(title=self.제목, body=self.몸, kind=self.갈래,
                    created=self.날짜, aliases=list(self.별칭), extra=남의것)


@dataclass
class 미리보기:
    """들이기 전에 **먼저 보여 주는 것.** 사람이 보고 나서 들인다."""

    뿌리: str = ""
    것들: list[들일것] = field(default_factory=list)
    못읽음: list[str] = field(default_factory=list)
    겹침: dict[str, list[str]] = field(default_factory=dict)      # 제목 → 온곳들
    이미있음: list[str] = field(default_factory=list)             # 창고에 그 제목이 이미 있다
    끊긴링크: list[tuple[str, str]] = field(default_factory=list)  # (온곳, 가리킨 이름)
    갈래셈: dict[str, int] = field(default_factory=dict)

    def 한줄(self) -> str:
        """사람에게 보여 줄 한 줄. **숫자를 앞세운다** — 들이기 전에 알아야 할 것이다."""
        말 = [f"{len(self.것들)}장"]
        if self.갈래셈:
            갈래 = " · ".join(f"{k} {v}" for k, v in
                             sorted(self.갈래셈.items(), key=lambda x: -x[1])[:4])
            말.append(갈래)
        if self.겹침:
            말.append(f"⚠ 제목 겹침 {len(self.겹침)}")
        if self.이미있음:
            말.append(f"⚠ 창고에 이미 있는 제목 {len(self.이미있음)}")
        if self.끊긴링크:
            말.append(f"끊긴 링크 {len(self.끊긴링크)}")
        if self.못읽음:
            말.append(f"못 읽음 {len(self.못읽음)}")
        return " · ".join(말)


def 제목뽑기(raw: str, 파일이름: str) -> str:
    """본문 첫 `# 표제`. 없으면 앞머리의 `제목`/`title`, 그것도 없으면 파일 이름.

    ★ 파일 이름을 먼저 보지 않는 까닭: 볼트의 이름은 `2026-08-05-ar-ai-agent-...` 같은
      **기계 이름**이다. 그대로 제목으로 삼으면 목록이 사람이 못 읽는 글자로 덮인다.
    """
    몸 = raw
    m = re.match(r"^---\r?\n(.*?)\r?\n---\r?\n?(.*)$", raw, re.S)
    앞 = m.group(1) if m else ""
    if m:
        몸 = m.group(2)
    표 = _표제.search(몸)
    if 표 and 표.group(1).strip():
        return 제목맞춤(표.group(1).strip())
    for 열쇠 in ("제목", "title"):
        n = re.search(rf"^{열쇠}:[ \t]*(.+?)[ \t]*$", 앞, re.M)
        if n and n.group(1).strip():
            return 제목맞춤(n.group(1).strip().strip("\"'"))
    return 제목맞춤(파일이름)


def 날짜뽑기(남의것: dict, 파일이름: str, 파일: Path | None = None) -> str:
    """`date` → 파일 이름 앞의 날짜 → 파일을 고친 때. **늘 뭔가를 돌려준다.**

    창고는 이 값으로 연/월 자리를 잡는다. 비면 「지금」이 되어 옛 글이 이 달에 쌓인다.
    """
    값 = str(남의것.get("date") or 남의것.get("날짜") or "").strip().strip("\"'")
    m = _날짜꼴.match(값)
    if not m:
        m = _앞날짜.match(파일이름)
    if m:
        해, 달 = m.group(1), m.group(2)
        날 = (m.group(3) if m.lastindex and m.lastindex >= 3 else None) or "01"
        return f"{해}-{달}-{날}T00:00:00Z"
    if 파일 is not None:
        try:
            return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(파일.stat().st_mtime))
        except OSError:
            pass
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def 한장(파일: Path, 뿌리: Path) -> 들일것 | None:
    """파일 하나를 읽어 들일 것으로. **못 읽으면 `None`** — 짐작해서 넣지 않는다."""
    raw = ingest.읽기(파일)
    if raw is None:
        return None
    # ★★ **줄끝을 먼저 고른다.** 볼트 119장 중 **24장이 윈도우에서 적혀 `\r\n`** 이었는데,
    #   창고의 앞머리 정규식은 `\A---\n` 이라 안 맞아 **`type` 94장 중 24장이 통째로 날아갔다**
    #   (갈래가 `dev-task` 33 → 24 로 줄고 「틀」이 23 → 40 으로 불어서 잡혔다).
    #   `read_text()` 는 줄끝을 고쳐 읽어 디버그에서는 멀쩡해 보인다 — 파일을 바이트로 읽는
    #   이 길에서만 난다. 같은 함정을 `mirror.py` 에서도 밟았다(줄끝 차이로 지문이 갈렸다).
    raw = unicodedata.normalize("NFC", raw).replace("\r\n", "\n").replace("\r", "\n")
    제목 = 제목뽑기(raw, 파일.stem)
    # 앞머리 풀기는 창고 것을 그대로 쓴다 — 두 군데서 풀면 언젠가 갈라진다
    임시 = Note.loads(제목, raw)
    남의것 = dict(임시.extra)
    # ★ `Note.loads` 는 앞머리가 없으면 갈래를 기본값 `note` 로 채운다 — 그것과
    #   **사람이 적은 `kind: note`** 를 구별해야 「날짜도 갈래도 없는 틀 문서」를 가려낼 수 있다.
    적힌갈래 = bool(re.search(r"^kind:[ \t]*\S", raw.split("---", 2)[1], re.M)) if _앞머리.match(raw) else False
    상대 = 파일.relative_to(뿌리).as_posix()
    안 = "/".join(상대.split("/")[:-1])
    마지막칸 = 안.split("/")[-1] if 안 else ""
    옛갈래 = str(남의것.pop("type", "") or (임시.kind if 적힌갈래 else "") or "").strip()
    # 폴더 → 옛 갈래 이름 → (마지막으로) 날짜 유무. 폴더가 가장 믿을 만하다.
    갈래 = 폴더갈래.get(마지막칸) or 폴더갈래.get(옛갈래) or ""
    끝난것 = 마지막칸 in 틀폴더 and not 갈래
    날짜 = 날짜뽑기(남의것, 파일.stem, 파일)
    # 날짜가 글에도 이름에도 없으면 **기록이 아니라 틀**이다(볼트에서 23장이 그랬다:
    # README·START_HERE·AGENTS·index·log·prompts/*). 갈래로 갈라 두면 평소 검색에 안 섞인다.
    if not 갈래:
        갈래 = wiki.기본갈래          # 모르면 `메모` — 나중에 합치기가 다시 본다
    # 남의 `status` 를 우리 `상태` 로. 원래 값은 그대로 둔다(둘 다로 찾을 수 있다).
    남의상태 = str(남의것.get("status") or "").split("#")[0].strip().lower()
    새상태 = 상태옮김.get(남의상태, "")
    if 끝난것:
        새상태 = "끝남"            # 옛 창고를 돌리던 틀 — 기준 노릇을 하면 안 된다
    if 새상태:
        남의것["상태"] = 새상태
    # ★ 남의 앞머리에 이미 `출처` 가 있으면 **비켜 준다.** 우리 규약과 이름만 같고 뜻이 다르다
    #   (실측: 「VC v0.1.32~33 작업(2026-09-02), 실측」). 지우지 않고 `원래출처` 로 옮긴다 —
    #   안 옮기면 규약 밖 값이 남아 살피기가 매번 걸고, 덮으면 적어 둔 것을 잃는다.
    남의출처 = str(남의것.get("출처") or "").strip()
    if 남의출처 and 남의출처 not in wiki.앞머리규약["출처"]:
        남의것.setdefault("원래출처", 남의출처)
        남의것.pop("출처", None)
    남의것.setdefault("출처", "볼트")
    별칭 = list(임시.aliases)
    # ★★ 별칭 둘: **파일 이름**과 **폴더까지 붙은 이름**. 옵시디언은 `[[post-build-qa]]` 로도
    #   `[[prompts/post-build-qa]]` 로도 같은 글을 가리킨다 — 실제 볼트에 둘 다 있었다
    #   (경로꼴 링크 6개가 끊긴 것으로 세어져 잡았다). 이 두 줄이 [[링크]] 775개를 잇는다.
    for 이름 in (제목맞춤(파일.stem), 제목맞춤(상대[:-3] if 상대.endswith(".md") else 상대)):
        if 이름 and 이름 != 제목 and 이름 not in 별칭:
            별칭.append(이름)
    return 들일것(제목=제목, 몸=임시.body, 갈래=갈래, 날짜=날짜, 별칭=별칭,
                남의것=남의것, 온곳=f"{뿌리.name}/{상대}")


def 살펴보기(뿌리: str | Path, 창고: Notes | None = None,
           끝: tuple[str, ...] = (".md",)) -> 미리보기:
    """들이기 **전에** 폴더를 훑어 무엇이 들어갈지 보여 준다. 창고는 안 건드린다."""
    뿌리 = Path(뿌리)
    본다 = 미리보기(뿌리=str(뿌리))
    이름들: dict[str, str] = {}       # 파일 이름 → 제목 (링크 이어짐을 재려고)
    for 파일 in ingest.훑기(뿌리, 끝):
        것 = 한장(파일, 뿌리)
        if 것 is None:
            본다.못읽음.append(파일.relative_to(뿌리).as_posix())
            continue
        본다.것들.append(것)
        이름들[제목맞춤(파일.stem)] = 것.제목
    자리: dict[str, list[str]] = {}
    for 것 in 본다.것들:
        자리.setdefault(것.제목, []).append(것.온곳)
        본다.갈래셈[것.갈래] = 본다.갈래셈.get(것.갈래, 0) + 1
    본다.겹침 = {t: v for t, v in 자리.items() if len(v) > 1}
    if 창고 is not None:
        본다.이미있음 = sorted(t for t in 자리 if 창고.read(t) is not None)
    아는이름 = set(이름들) | {것.제목 for 것 in 본다.것들}
    for 것 in 본다.것들:
        for 가리킨, _ in parse_links(것.몸):
            머리 = 제목맞춤(str(가리킨).split("#")[0].split("|")[0].strip())
            if 머리 and 머리 not in 아는이름:
                본다.끊긴링크.append((것.온곳, 머리))
    return 본다


def 들이기(창고: Notes, 본다: 미리보기, 덮기: bool = False) -> dict:
    """미리 본 것을 창고에 넣는다. **이미 있는 제목은 기본으로 건드리지 않는다.**

    ★ 덮지 않는 까닭: 들이기는 한 번에 백 장이 움직인다. 같은 제목이 하나라도 있으면
      사람이 적은 글이 남의 폴더 것으로 조용히 덮인다 — 되돌릴 수 없는 종류다.
    """
    넣음, 건너뜀, 터짐 = [], [], []
    for 것 in 본다.것들:
        if not 덮기 and 창고.read(것.제목) is not None:
            건너뜀.append(것.제목)
            continue
        try:
            창고.write(것.글로())
            넣음.append(것.제목)
        except OSError as e:
            터짐.append((것.온곳, str(e)))
    return {"넣음": 넣음, "건너뜀": 건너뜀, "터짐": 터짐}


def 되돌리기(창고: Notes, 볼트이름: str) -> list[str]:
    """그 폴더에서 들인 글을 **한꺼번에 뺀다.** 사람이 뒤에 적은 글은 안 건드린다."""
    뺄것 = []
    for 파일 in Path(창고.root).rglob("*.md"):
        if 파일.name.startswith("."):
            continue
        try:
            raw = 파일.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        글 = Note.loads(파일.stem, raw)
        온곳 = str(글.extra.get(온곳열쇠, ""))
        if 온곳.startswith(f"{볼트이름}/"):
            뺄것.append(글.title if 글.title else 파일.stem)
    뺀것 = []
    for 제목 in 뺄것:
        if 창고.delete(제목):
            뺀것.append(제목)
    return 뺀것


def _self_check() -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        뿌리 = Path(tmp) / "내볼트"
        (뿌리 / "wiki" / "errors").mkdir(parents=True)
        (뿌리 / "wiki" / "errors" / "2026-06-12-qt-korean-path.md").write_text(
            "---\ntype: error\ndate: 2026-06-12\nstatus: done\nsource: 대화\n---\n"
            "# Qt 가 한글 경로를 버린다\n\n[[2026-08-05-grilling]] 을 보라. #긴급\n"
            "색은 #D35400 이다.\n", encoding="utf-8")
        (뿌리 / "wiki" / "errors" / "2026-08-05-grilling.md").write_text(
            "---\ntype: guideline\ndate: 2026-08-05\n---\n# 그릴링 규칙\n\n본문.\n",
            encoding="utf-8")
        (뿌리 / "README.md").write_text("# 볼트 안내\n\n틀 문서다. [[없는 글]] 참고.\n",
                                       encoding="utf-8")
        # ★★ **윈도우에서 적은 파일(CRLF).** 실제 볼트 119장 중 24장이 이랬고, 줄끝을
        #   안 고르면 앞머리가 통째로 안 읽혀 `type` 이 날아간다(실기에서 잡았다).
        (뿌리 / "wiki" / "errors" / "2026-07-01-windows.md").write_bytes(
            "---\r\ntype: dev-task\r\ndate: 2026-07-01\r\nstatus: active\r\n---\r\n"
            "# 윈도우에서 적은 글\r\n\r\n본문.\r\n".encode("utf-8"))

        본다 = 살펴보기(뿌리)
        assert len(본다.것들) == 4, [것.제목 for 것 in 본다.것들]
        # 줄끝이 CRLF 여도 앞머리가 읽혀야 한다
        윈 = next(것 for 것 in 본다.것들 if 것.제목 == "윈도우에서 적은 글")
        # ★ **폴더가 `type` 을 이긴다.** 날짜가 없어 `type` 이 빠진 글도 폴더는 제 자리에
        #   있었다(실측). 둘이 어긋나면 폴더를 믿는다 — 여기서는 `wiki/errors` 라 `오류`.
        assert 윈.갈래 == "오류", f"폴더를 안 믿는다: {윈.갈래}"
        assert 윈.남의것.get("status") == "active", "남의 status 를 지웠다"
        assert 윈.남의것.get("상태") == "살아있음", f"상태를 새 규약으로 안 옮겼다: {윈.남의것}"
        assert 윈.남의것.get("출처") == "볼트", 윈.남의것
        # 남의 `출처` 는 비켜 주되 **안 지운다**
        (뿌리 / "wiki" / "errors" / "2026-07-02-남의출처.md").write_text(
            "---\ntype: error\ndate: 2026-07-02\n출처: 어느 세션에서 실측\n---\n"
            "# 남의 출처가 있는 글\n\n본문.\n", encoding="utf-8")
        남 = next(것 for 것 in 살펴보기(뿌리).것들 if 것.제목 == "남의 출처가 있는 글")
        assert 남.남의것.get("출처") == "볼트", 남.남의것
        assert 남.남의것.get("원래출처") == "어느 세션에서 실측", 남.남의것
        assert 윈.날짜.startswith("2026-07"), 윈.날짜
        assert 윈.남의것.get("status") == "active", 윈.남의것
        assert "\r" not in 윈.몸, "본문에 윈도우 줄끝이 남았다"
        제목들 = {것.제목 for 것 in 본다.것들}
        # ★★ **제목은 본문 표제다.** 파일 이름을 쓰면 목록이 기계 이름으로 덮인다.
        assert "Qt 가 한글 경로를 버린다" in 제목들, 제목들
        assert "2026-06-12-qt-korean-path" not in 제목들, "파일 이름이 제목이 됐다"
        하나 = next(것 for 것 in 본다.것들 if 것.제목 == "Qt 가 한글 경로를 버린다")
        # ★★ **파일 이름은 별칭으로.** 이 한 줄이 [[링크]]를 잇는다.
        assert "2026-06-12-qt-korean-path" in 하나.별칭, 하나.별칭
        # 폴더까지 붙은 이름으로도 가리킬 수 있어야 한다(옵시디언이 그렇게 쓴다).
        # ※ `/` 는 파일 이름에 못 쓰므로 창고가 전각 `／` 로 모은다 — 찾는 쪽도 같은 길을 지난다.
        assert 제목맞춤("wiki/errors/2026-06-12-qt-korean-path") in 하나.별칭, 하나.별칭
        assert 하나.갈래 == "오류", 하나.갈래       # 폴더(`wiki/errors`) → 새 갈래
        assert 하나.날짜.startswith("2026-06"), 하나.날짜            # date → 연/월 자리
        assert 하나.남의것.get("status") == "done", 하나.남의것       # 남의 앞머리는 지고 간다
        assert "type" not in 하나.남의것, "갈래로 옮긴 것이 두 번 적힌다"
        # ★ **쪼개지 않는다.** ingest 는 110/119 장을 도막냈다.
        assert "[[2026-08-05-grilling]]" in 하나.몸 and "#긴급" in 하나.몸, 하나.몸
        assert not 하나.몸.lstrip().startswith("---"), "앞머리가 본문에 남았다"
        # ★ 창고 **맨 위**의 글은 그 창고를 돌리던 틀이다 — 새 기준과 경쟁하면 안 되므로
        #   `메모` + `상태: 끝남` 으로 내려 둔다(오너 2026-09-21: 「새 창고 기준이 메인」).
        틀 = next(것 for 것 in 본다.것들 if 것.제목 == "볼트 안내")
        assert 틀.갈래 == wiki.기본갈래, 틀.갈래
        assert 틀.남의것.get("상태") == "끝남", 틀.남의것
        # 모든 갈래가 **새 기준 안**에 있어야 한다 — 옛 이름이 섞이면 기준이 둘이 된다
        for 것 in 본다.것들:
            assert wiki.아는갈래(것.갈래) and 것.갈래 not in ("dev-task", "error"), 것.갈래
        # 끊긴 링크는 있는 그대로 알린다 — 이어진 것을 끊겼다고 세면 안 된다
        끊긴 = {이름 for _, 이름 in 본다.끊긴링크}
        assert 끊긴 == {"없는 글"}, 본다.끊긴링크
        assert not 본다.겹침 and not 본다.못읽음, (본다.겹침, 본다.못읽음)
        assert 본다.갈래셈.get("오류") == 3 and 본다.갈래셈.get(wiki.기본갈래) == 1, 본다.갈래셈
        assert "4장" in 본다.한줄() and "오류" in 본다.한줄(), 본다.한줄()

        창고 = Notes(Path(tmp) / "창고")
        난것 = 들이기(창고, 본다)
        assert len(난것["넣음"]) == 4 and not 난것["터짐"], 난것
        들어온것 = 창고.read("Qt 가 한글 경로를 버린다")
        assert 들어온것 is not None and 들어온것.kind == "오류"
        assert 들어온것.extra.get("status") == "done", 들어온것.extra
        assert 들어온것.extra.get(온곳열쇠, "").startswith("내볼트/"), 들어온것.extra
        # ★★ **별칭으로 열린다** = 볼트의 [[링크]]가 이어진다는 뜻이다
        별칭으로 = 창고.read("2026-06-12-qt-korean-path")
        assert 별칭으로 is not None and 별칭으로.title == "Qt 가 한글 경로를 버린다", 별칭으로
        경로로 = 창고.read("wiki/errors/2026-06-12-qt-korean-path")
        assert 경로로 is not None and 경로로.title == "Qt 가 한글 경로를 버린다", "경로꼴 링크가 안 닿는다"
        # 색상 코드는 태그가 아니다(창고가 이미 거른다) — 들이기가 그것을 깨지 않았는지
        assert "긴급" in 들어온것.tags() and "D35400" not in 들어온것.tags(), 들어온것.tags()
        # 연/월 자리
        자리 = 창고.path_of(들어온것.title, 들어온것.created)
        assert 자리.parent.name == "06" and 자리.parent.parent.name == "2026", 자리

        # 두 번 들여도 사람 글을 안 덮는다
        창고.write(Note(title="볼트 안내", body="내가 나중에 적은 글"))
        다시 = 들이기(창고, 살펴보기(뿌리))
        assert "볼트 안내" in 다시["건너뜀"], 다시
        assert 창고.read("볼트 안내").body.strip() == "내가 나중에 적은 글", "사람 글을 덮었다"

        # 창고에 이미 있는 제목은 **미리 보여 준다**
        assert "볼트 안내" in 살펴보기(뿌리, 창고).이미있음

        # 한꺼번에 되돌린다 — 사람이 적은 글은 남는다
        뺀것 = 되돌리기(창고, "내볼트")
        assert len(뺀것) == 4, 뺀것
        assert 창고.read("Qt 가 한글 경로를 버린다") is None, "되돌렸는데 남았다"
        assert 창고.read("볼트 안내") is not None, "사람이 적은 글까지 뺐다"

    print("vault self-check 통과")


if __name__ == "__main__":
    import sys

    if "--check" in sys.argv:
        _self_check()
