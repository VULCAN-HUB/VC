"""항목 저장소 — 마크다운이 원본, SQLite는 인덱스 (결정 29·30).

항목 하나가 파일 하나다. 기억·스킬·장소·물건처럼 **지속되는 개념**만 항목이 되고,
지시 이력은 여기 들어오지 않는다(그쪽은 store.py의 학습 로그).

인덱스는 **언제든 파일에서 다시 만들 수 있다.** 동기화가 어긋나도 데이터가 죽지 않는다.
그래서 인덱스를 지우고 재생성하는 것이 항상 안전한 복구 수단이다.

파일 형식:

    ---
    id: 01J...
    kind: preference
    pinned: true
    created: 2026-08-05T12:00:00Z
    ---
    난 아이스만 마신다. [[카페-단골]]과 함께 본다.
"""

from __future__ import annotations
import paths
import wiki

import json
import os
import random
import hashlib
import re
import unicodedata
import shutil
import stat
import sqlite3
from concurrent.futures import ThreadPoolExecutor
import threading
import traceback
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

# [[대상]] · [[대상#소제목]] · [[대상|보이는 글자]] 를 한 번에 읽는다.
# ★ 표 안에서는 `|` 가 칸을 가르므로 옵시디언은 `[[제목\|보일 말]]` 로 적는다 — `\|` 도 받는다.
#   안 받으면 제목 끝에 `\` 가 붙어 끊긴 링크가 됐다(제품 보유 목록 표).
LINK_RE = re.compile(r"\[\[([^\]\[|#]+?)(?:#([^\]\[|\\]+))?(?:\\?\|([^\]\[]+))?\]\]")

# ![[노트]] · ![[노트#소제목]] — 끼워 보기. 링크와 같은 꼴이라 연결로도 잡힌다.
EMBED_RE = re.compile(r"!\[\[([^\]\[|#]+?)(?:#([^\]\[|\\]+))?(?:\\?\|[^\]\[]+)?\]\]")

# 태그 #이름. 줄 첫머리의 #은 마크다운 제목이라 뺀다(정규식 밖에서 거른다).
# 숫자만 있는 것도 뺀다 — "#1"은 태그가 아니라 번호다.
# 태그에 쓸 수 있는 글자는 **글자·숫자·밑줄·붙임표·빗금**뿐이다(옵시디언 규칙).
# 아무 글자나 받으면 실제 기록에서 `#D35400**`·`#0E1116+코발트` 같은 부스러기가
# 태그로 잡힌다 — 마크다운 강조나 색 코드가 그대로 딸려 들어온 것이다.
TAG_RE = re.compile(r"(?<![\w#/])#([\w/-]{1,40})")
CODE_RE = re.compile(r"```.*?```|`[^`]*`", re.S)
FRONTMATTER_RE = re.compile(r"\A---\n(.*?)\n---\n?(.*)\Z", re.S)

# ★★ **적는 판. 모든 항목이 이걸 달고 저장된다.**
#
# 없으면 **0판**이다 — 「필드가 없다 = 아직 안 옮겼다」가 그대로 질의가 되므로
# 옛 항목에 소급해 채울 필요가 없다. 새로 쓰는 것부터 달면 된다.
#
# 왜 필요한가: 고침이 옛 자료에 소급되지 않는데, **무엇이 아직 안 고쳐졌나를
# 물어볼 길이 없었다.** 제목의 `--` 도 옛 앞머리 두 겹도 **찾다가 눈에 걸려야**
# 알았다. 판번호가 있으면 대상만 골라 고칠 수 있고 「몇 %가 현재 판인가」가
# 상시로 보인다. 남은 수단이 「통째로 다시 붓기」뿐이던 까닭이 이것이 없어서다.
#
# 올릴 때: 저장 꼴이 바뀌어 **옛 항목을 고쳐야 하는 변경**일 때만 올린다.
# 화면만 바뀌는 것은 안 올린다 — 판번호가 흔들리면 적합률이 뜻을 잃는다.
적는판 = 1


def _앞머리값(글: str) -> object:
    """앞머리 값 한 개를 푼다. JSON 이면 JSON 으로, 아니면 글자 그대로."""
    if not 글:
        return ""
    try:
        return json.loads(글)
    except (ValueError, TypeError):
        return 글.strip("\"'")
class 원문그대로(str):
    """앞머리에서 **우리가 못 읽는 덩이**. 값을 모르지만 글자를 그대로 되돌려 쓴다.

    중첩 사전(`obsidian:` 아래 들여쓴 줄들)·여러 줄 글(`note: >`)이 여기 온다.
    `str` 을 물려받아 아무 데서나 글자로 다뤄지되, 다시 쓸 때 JSON 으로 감싸지 않는다.
    """


def _앞머리풀기(글: str) -> dict:
    """앞머리 한 덩이를 사전으로. **옵시디언이 쓰는 블록 목록 꼴을 받는다.**

    ★★ 옵시디언은 태그·별칭을 이렇게 적는다:

        tags:
          - 할일
          - 프로젝트/VC

    한 줄씩 `k: v` 로만 읽던 때는 이것이 `tags: ""` 가 되어, **다시 쓸 때 사람이 적은
    태그가 통째로 사라졌다**(재 보고 찾았다). 별칭도 같아서 옵시디언 별칭이 죽었다.
    """
    풀림: dict = {}
    줄들 = 글.splitlines()
    i = 0
    while i < len(줄들):
        줄 = 줄들[i].rstrip()
        i += 1
        if not 줄.strip() or 줄.lstrip().startswith("#"):
            continue
        if 줄 != 줄.lstrip() or ":" not in 줄:
            continue                      # 들여쓴 줄은 위 열쇠가 이미 먹었다
        열쇠, _, 값 = 줄.partition(":")
        열쇠, 값 = 열쇠.strip(), 값.strip()
        if 값 in (">", "|", ">-", "|-", ">+", "|+"):
            # ★ 여러 줄 글(`note: >` 아래 들여쓴 줄들). 값을 못 읽지만 **글자 그대로 안고 간다** —
            #   전에는 `note: ">"` 가 되어 아래 줄들이 통째로 사라졌다.
            묶음 = [줄]
            while i < len(줄들) and (not 줄들[i].strip() or 줄들[i][:1] in (" ", "	")):
                묶음.append(줄들[i])
                i += 1
            풀림[열쇠] = 원문그대로(chr(10).join(묶음[1:]))
            풀림[열쇠 + "~표시"] = 값        # 다시 쓸 때 `>` 를 되살린다
            continue
        if 값:
            # `tags: [할일, 회의]` — 한 줄 대괄호 목록. 그냥 글자로 두면 태그가
            # `[할일` · `회의]` 로 잘려 대괄호가 이름에 섞인다(재 보고 찾았다).
            if 값.startswith("[") and 값.endswith("]"):
                안 = 값[1:-1].strip()
                풀림[열쇠] = [_앞머리값(조각.strip()) for 조각 in 안.split(",") if 조각.strip()]
            else:
                풀림[열쇠] = _앞머리값(값)
            continue
        # 값이 비었다 — 아래 줄들이 그 값이다.
        모음 = []
        while i < len(줄들) and 줄들[i].strip().startswith("- "):
            모음.append(_앞머리값(줄들[i].strip()[2:].strip()))
            i += 1
        if 모음:
            풀림[열쇠] = 모음
            continue
        # ★★ **우리가 못 읽는 꼴(중첩 사전·여러 줄 글)** 은 **글자 그대로 안고 간다.**
        #   전에는 `obsidian: ""` 로 뭉개져, 다시 쓰는 순간 사람이 적은 것이 사라졌다.
        #   읽지는 못해도 **없애지는 않는다** — 원본이 원본이라는 규칙이 여기도 같다.
        묶음 = []
        while i < len(줄들) and (not 줄들[i].strip() or 줄들[i][:1] in (" ", "	")):
            묶음.append(줄들[i])
            i += 1
        풀림[열쇠] = 원문그대로(chr(10).join(묶음)) if 묶음 else ""
    return 풀림


UNSAFE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

# 첨부로 보는 확장자. **첨부는 항목이 아니다** — `![[사진.png]]`을 노트 링크로 세면
# "아직 없는 것"에 사진 이름이 끝없이 쌓이고 그래프에 유령 점이 생긴다.
# ★ 폰으로 남기는 모든 기록(결정 16) — 아이폰 사진은 .heic, 영상은 .mov·.mp4, 녹음은 .m4a 로 온다.
#   그림만 받던 목록이라 폰 사진이 「받는 파일 꼴이 아니다」로 막혔다(4단계). 원본을 그대로 둔다.
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg"}
PHONE_MEDIA_EXT = {".heic", ".heif", ".mov", ".mp4", ".m4v", ".m4a", ".aac", ".mp3", ".wav"}
ATTACH_EXT = IMAGE_EXT | {".pdf"} | PHONE_MEDIA_EXT
ATTACH_DIR = "_첨부"

# 지난 판을 두는 곳. 점으로 시작해 **옵시디언에서 안 보인다** — 기계가 챙기는 것이지
# 사람이 뒤적일 폴더가 아니다. 색인에서도 통째로 뺀다.
HISTORY_DIR = ".이력"
HISTORY_KEEP = 20          # 항목당 남길 판 수. 20년이라도 무한정 쌓으면 안 된다
HISTORY_GAP_SEC = 300      # 이 안에 또 저장되면 새 판을 안 만든다(치는 대로 저장이라)

# 서식(템플릿)을 두는 곳. 밑줄로 시작해 항목 목록에서 눈에 안 띄되, 사람이 열어
# 고칠 수 있게 **보이는** 폴더로 둔다(`_첨부`와 같은 자리).
TEMPLATE_DIR = "_서식"
# 설정 「기계 기록 보기 — 둘 다」 일 때 VC 가 요약을 적는 자리(결정 17). 기계가 쓴 글이라 항목으로 안 센다.
VC_LOG_DIR = "_VC기록"

# 서식 안에서 갈아 끼우는 자리. 옵시디언 표기도 같이 받는다.
SLOT_RE = re.compile(r"\{\{\s*(날짜|시각|제목|date|time|title)\s*\}\}", re.I)          # 노트 폴더 안. `_`로 시작해 항목 폴더와 눈으로 갈린다


# 글을 읽을 때 차례로 시도할 것들. 20년 치에는 딴 도구가 만든 옛 파일이 섞인다 —
# 윈도우 한글판에서 만든 것은 대개 cp949 다.
# `utf-8-sig` 가 먼저다. 윈도우 도구(메모장·PowerShell `Set-Content -Encoding UTF8`)는
# 맨 앞에 BOM 을 붙이는데, 그냥 `utf-8` 로 읽으면 그 BOM 이 **글자로 남는다.**
# 그러면 첫 줄이 `---` 가 아니게 되어 **프론트매터가 통째로 안 읽힌다** — 별칭·태그·
# 종류가 사라진다. BOM 이 없는 파일도 `utf-8-sig` 로 똑같이 읽히므로 앞에 둔다.
ENCODINGS = ("utf-8-sig", "utf-8", "cp949")


class Vanished(FileNotFoundError):
    """읽으려는 사이에 사라졌다. 남이 지운 것이다 — 없는 것으로 치면 된다."""


def read_text(path: Path) -> str:
    """어떤 파일이든 글자로 만든다. **읽기가 실패해서 색인이 멈추면 안 된다.**

    UTF-8이 아닌 파일 하나가 색인 전체를 죽인 적이 있다. 20년 볼트에 옛 파일 하나만
    섞여도 그때부터 아무것도 색인이 안 됐다 — 그 뒤 파일들이 통째로 사라진 채로.

    마지막에는 못 읽는 바이트를 바꿔치기해서라도 읽는다. 글자가 몇 개 깨져 보이는 것이
    항목이 아예 없어지는 것보다 낫다.
    """
    # **있는지 보고 읽는 사이에 사라질 수 있다.** 화면·AI·옵시디언이 같은 볼트를
    # 함께 쓰므로, 한쪽이 지우는 순간 다른 쪽이 그 파일을 만진다. 실제로 여럿이
    # 동시에 쓰는 시험에서 `FileNotFoundError` 로 실이 통째로 죽었다.
    try:
        raw = path.read_bytes()
    except FileNotFoundError as err:
        raise Vanished(str(path)) from err
    for enc in ENCODINGS:
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        text = raw.decode("utf-8", errors="replace")
    # **줄바꿈을 한 가지로 맞춘다.** 파이썬 텍스트 모드가 해 주던 일인데, 바이트로
    # 읽으면 안 해 준다. 윈도우에서 쓴 파일은 CR+LF 라, 안 맞추면 프론트매터
    # 파서가 CR 에 걸려 **별칭·태그가 통째로 사라진다**(자체점검이 잡았다).
    return text.replace(chr(13) + chr(10), chr(10)).replace(chr(13), chr(10))


# 뜻으로 찾기 위한 벡터. **낱말이 안 맞아도** 찾으라고 두는 것이다 —
# "작년에 배포 엎었던 거"처럼 사람은 낱말이 아니라 모양으로 기억한다.
#
# 항목 하나에 벡터 하나. 처음엔 글을 조각내 조각마다 벡터를 뒀는데(겹쳐 자르고
# 소제목까지 붙여서), **정답을 아는 물음 12개로 재보니 그게 훨씬 나빴다**:
#
#     낱말만            1등  0/12
#     제목+앞200자 하나   1등  7/12 ·   2초 (2만 개면 8분)
#     제목붙인 조각 740개  1등  1/12 · 127초 (2만 개면 6.6시간)
#
# 조각이 많은 문서(18만 자짜리 기록 하나가 176조각)가 무슨 물음에나 끼어들어
# 흐렸다. 글을 더 넣을수록 나빠지기도 했다(앞 800자면 3/12로 떨어진다) —
# 작고 양자화된 모델이 긴 글에 흐려진다.
VECTOR_SCHEMA = """
CREATE TABLE IF NOT EXISTS vectors (
    path TEXT PRIMARY KEY,
    vec  BLOB NOT NULL,
    -- 제목만 따로 한 벌 더. 제목이 답일 때와 본문이 답일 때가 다르다.
    tvec BLOB
);
"""

# 벡터로 만들 글의 길이. 재서 고른 값이다(위 표).
CARD_CHARS = 200
EMBED_TOKENS = 192   # 200자면 한글 기준 110토큰쯤. 제목이 길어도 남게 조금 넉넉히
EMBED_BATCH = 16     # 짧은 글이라 넉넉히 묶어도 메모리가 안 터진다


def meaning_card(title: str, body: str) -> str:
    """뜻을 재는 데 쓰는 글. **제목 + 앞부분**이 전부다."""
    head = (body or "").strip()[:CARD_CHARS]
    return title + chr(10) + head if head else title


def _call_embed(embed, texts: list[str], prefix: str):
    """접두사를 받는 임베더면 넘기고, 아니면 그냥 부른다.

    밖에서 끼우는 물건이라 어떤 꼴일지 모른다. 못 받는 것에 억지로 넘겨 터지면
    뜻 검색이 통째로 죽는다.
    """
    try:
        return embed(texts, prefix)
    except TypeError:
        return embed(texts)


def _pack(vec) -> bytes:
    """벡터를 바이트로. **반정밀도로 줄인다.**

    가까운 정도를 재는 데 소수점 아래 자리가 다 필요하지 않다. 2만 개면 벡터를
    올려 두는 데만 186MB가 드는데, 절반이면 93MB다. 순위는 바뀌지 않는다.
    """
    import numpy as np

    return np.asarray(vec, dtype="float16").tobytes()


def _read(path: Path) -> str | None:
    """읽기만 한다. 읽는 사이 사라진 파일 하나 때문에 전체 색인이 멈추면 안 된다."""
    try:
        return read_text(path)
    except OSError:
        return None


TERM_RE = re.compile(r"[\w가-힣]+")  # 물음을 낱말로 끊는다. 기호는 버린다

# 물음 한 조각: `tag:할일` · `"정확한 구절"` · `-빼기` · 그냥 낱말.
PIECE_RE = re.compile(r'(-?)(?:(\w+):)?(?:"([^"]*)"|(\S+))')

# 좁히는 말과 그것이 걸리는 곳. 여기 없는 이름(`tag:`가 아닌 `xyz:`)은 **그냥 낱말
# 둘**로 친다 — 값만 남기고 이름을 버리면 `결정:22` 같은 진짜 글자가 조용히 사라진다.
def 라이크(값: str) -> str:
    """`LIKE` 에 넣을 글자에서 **와일드카드를 막는다.**

    ★★ SQL `LIKE` 에서 `_` 는 「아무 글자 하나」, `%` 는 「아무 글자들」이다. 그대로 넣으면
      **찾는 글자가 아닌 것이 걸린다** — 실제로 `path:_정리` 가 「_정리 폴더의 1장」 대신
      「제목에 '정리'가 든 3장」까지 **4장**을 내놓았다(폴더 칸을 만들다 잡았다).
      창고에는 `_서식`·`_정리` 처럼 밑줄로 시작하는 폴더가 있고, 제목·태그에도 들어갈 수 있다.
      쓰는 쪽은 반드시 `ESCAPE '\\'` 를 같이 적는다.
    """
    return (str(값).replace("\\", "\\\\")
            .replace("%", "\\%").replace("_", "\\_"))


def 앞머리값(v) -> str:
    """앞머리 값을 **찾을 수 있는 한 줄**로 편다.

    옵시디언 앞머리는 글자·숫자·참거짓뿐 아니라 목록(`tags: [a, b]`)도 온다.
    찾을 때 필요한 건 「그 말이 들었나」이므로 목록은 사이를 띄워 붙인다.
    """
    if isinstance(v, (list, tuple)):
        return " ".join(앞머리값(x) for x in v)
    if isinstance(v, dict):
        return " ".join(f"{k} {앞머리값(x)}" for k, x in v.items())
    return str(v).strip()


NARROW = {
    "tag": "태그", "태그": "태그",
    "path": "경로", "경로": "경로",
    "kind": "종류", "종류": "종류",
    "year": "해", "해": "해", "년": "해",
    # 옵시디언의 `file:` 자리다. **제목만** 보고 싶을 때가 있다 —
    # 본문에 그 말이 많은 글이 제목이 그 말인 글을 덮어 버리기 때문이다.
    "title": "제목", "제목": "제목", "file": "제목",
}


class Ask:
    """물음을 뜯어 놓은 것. 낱말·구절·좁히는 말·뺄 것."""

    __slots__ = ("terms", "phrases", "narrow", "minus_terms", "minus_phrases", "raw", "또는")

    def __init__(self, raw: str, 앞머리이름: frozenset | set | None = None) -> None:
        self.raw = raw
        # ★ **「이것 아니면 저것」도 찾을 수 있어야 한다.** 옵시디언은 `TODO OR FIXME` 가
        #   되는데 우리는 낱말을 늘 AND 로 묶어 **0건**이었다. 「하나라도 든 것」은
        #   흔한 물음이다(급한 것 모으기·여러 이름으로 불리는 것). 한글 「또는」도 받는다.
        #   ※ 낱말로 안 쓰이게 조각내기 **전에** 뽑아낸다.
        self.또는 = bool(re.search(r"(?:(?<=\s)|^)(?:OR|또는)(?=\s)", raw))
        if self.또는:
            raw = re.sub(r"(?:(?<=\s)|^)(?:OR|또는)(?=\s)", " ", raw)
        self.terms: list[str] = []
        self.phrases: list[str] = []
        self.narrow: list[tuple[str, str]] = []
        self.minus_terms: list[str] = []
        self.minus_phrases: list[str] = []
        for minus, key, quoted, bare in PIECE_RE.findall(raw):
            word = quoted if quoted else bare
            if not word:
                continue
            kind = NARROW.get((key or "").lower())
            # ★★ **창고가 실제로 지닌 앞머리면 그 값으로 찾는다**(오너 2026-09-20).
            #   볼트마다 앞머리가 달라 이름을 코드에 손으로 적어 둘 수 없다 — 창고를
            #   보고 가른다. 없는 이름은 **지금까지처럼 낱말로** 친다(글 속의 `C:\` 나
            #   `09:30` 을 찾을 때 0장이 되면 안 된다).
            if kind is None and key and 앞머리이름 and key in 앞머리이름:
                kind = "앞머리:" + key
            if kind and not minus:
                self.narrow.append((kind, word))
                continue
            if kind and minus:
                self.narrow.append(("빼기:" + kind, word))
                continue
            if key:                      # 모르는 이름은 통째로 낱말로 친다
                word = f"{key}:{word}"
            if quoted:
                (self.minus_phrases if minus else self.phrases).append(word)
            else:
                # 낱말 안의 기호는 FTS가 못 읽는다. 쪼개서 다 들어가게 한다.
                bits = TERM_RE.findall(word)
                (self.minus_terms if minus else self.terms).extend(bits)

    def empty(self) -> bool:
        return not (self.terms or self.phrases or self.narrow)

    def plain(self) -> str:
        """좁히는 말(`tag:할일`)을 뺀 **사람 말만**.

        뜻으로 찾을 때 문법 글자를 그대로 넘기면 벡터가 그것도 뜻으로 읽는다.
        """
        return " ".join([*self.phrases, *self.terms]).strip()

    def match(self) -> str:
        """FTS5에 줄 말. 없으면 빈 문자열."""
        want = ['"%s"*' % t for t in self.terms]
        want += ['"%s"' % p.replace('"', "") for p in self.phrases]
        out = (" OR " if self.또는 else " AND ").join(want)
        drop = ['"%s"*' % t for t in self.minus_terms]
        drop += ['"%s"' % p.replace('"', "") for p in self.minus_phrases]
        if drop:
            gone = " OR ".join(drop)
            out = f"({out}) NOT ({gone})" if out else ""
        return out
HEX_COLOR = re.compile(r"(?i)[0-9a-f]{3}|[0-9a-f]{4}|[0-9a-f]{6}|[0-9a-f]{8}")


def 카드미리보기(몸: str, 길이: int = 140) -> str:
    """폰 목록 카드의 두 줄 — 끼움(`![[…]]`) · 태그만 있는 줄 · 앞머리 · 목록 기호를 걷고 줄을 ` · ` 로 잇는다.

    ★ 그냥 첫 줄을 쓰면 서식으로 쓴 글이 모두 「- 제품명 : …」 한 줄로만 보였다(시뮬레이터 점검 2026-09-18).
    """
    몸 = re.sub(r"(?s)^---\n.*?\n---\n", "", 몸)
    몸 = re.sub(r"(?s)%%.*?%%", " ", 몸)   # 옵시디언 주석(사진 글자 등)은 안 보인다
    몸 = re.sub(r"!\[\[[^\]]*\]\]", " ", 몸)
    # `[[제목]]` · `[[제목#소제목|보일 말]]` 은 보일 말만 — 미리보기에 기호가 그대로 남았다(시뮬레이터 점검)
    몸 = re.sub(r"\[\[([^\]|#]*)(?:#[^\]|]*)?(?:\|([^\]]*))?\]\]", lambda m: m.group(2) or m.group(1), 몸)
    조각 = []
    for 줄 in 몸.splitlines():
        줄 = re.sub(r"^\s*(?:[-*+]|\d+\.)\s+(?:\[[ xX]\]\s+)?", "", 줄).strip()
        줄 = re.sub(r"^#+\s+", "", 줄)
        if not 줄 or re.fullmatch(r"(?:#[^\s#]+\s*)+", 줄):
            continue
        조각.append(re.sub(r"\s*:\s*", ": ", 줄, count=1) if " : " in 줄 else 줄)
        if sum(len(c) for c in 조각) > 길이:
            break
    글 = " · ".join(조각)
    return 글[:길이] + ("…" if len(글) > 길이 else "")


def is_attachment(name: str) -> bool:
    return Path(name).suffix.lower() in ATTACH_EXT


INDEX_SCHEMA = """
CREATE TABLE IF NOT EXISTS notes (
    path      TEXT PRIMARY KEY,
    id        TEXT NOT NULL,
    title     TEXT NOT NULL,
    -- 우리가 마지막으로 **쓴 글**의 지문. 다음에 덮어쓰기 전에 파일이 그것과
    -- 같은지 본다. 다르면 그 사이 **밖에서 누가 고친 것**이므로 지난 판을
    -- 반드시 남긴다(5분 간격 규칙을 건너뛴다).
    -- ★ **비었으면 「밖에서 고쳤다」로 친다.** 색인은 다시 만들 수 있는 파생물이라
    -- 지문이 없을 수 있는데, 모르는 쪽을 「안전」으로 읽으면 사람 손질이 조용히
    -- 지워진다. 모르면 남기는 쪽이 싸다 — 잘못 남기면 이력이 한 판 늘 뿐이다.
    wrote     TEXT NOT NULL DEFAULT '',
    kind      TEXT NOT NULL,
    pinned    INTEGER NOT NULL DEFAULT 0,
    created   TEXT NOT NULL,
    mtime     REAL NOT NULL,
    body      TEXT NOT NULL,
    use_count INTEGER NOT NULL DEFAULT 0,
    used_at   REAL,
    -- 벡터를 만들 때의 mtime. 다르면 다시 만들어야 한다는 뜻이다.
    vec_mtime REAL NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_notes_kind ON notes (kind);
-- 제목으로 찾는 일이 잦다(링크 해석). PK는 경로라 제목엔 색인이 따로 필요하다.
CREATE INDEX IF NOT EXISTS idx_notes_title ON notes (title);

CREATE TABLE IF NOT EXISTS links (
    src     TEXT NOT NULL,
    dst     TEXT NOT NULL,
    heading TEXT NOT NULL DEFAULT '',
    -- 0 = 사람이 손으로 이은 진한 선, 1 = 흡수해 온 글에 들어 있던 흐린 선.
    -- ★ 예전에는 흡수 글의 `[[ ]]` 를 **아예 안 넣었다.** 진한 선과 섞이면
    -- 「사람이 이은 것」의 뜻이 흐려진다는 까닭이었는데, 실제 자료가 사실상
    -- 전부 흡수분이라 **그물이 통째로 비었다**(3142장에 이음 0). 안 넣는 대신
    -- 갈라서 넣는다 — 원문 문자열은 본문에 있으니 언제든 다시 만들 수 있다.
    흐림    INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (src, dst, heading)
);
CREATE INDEX IF NOT EXISTS idx_links_dst ON links (dst);

-- 태그. 같은 항목에 같은 태그가 여러 번 나와도 한 줄이다.
CREATE TABLE IF NOT EXISTS tags (
    title TEXT NOT NULL,
    tag   TEXT NOT NULL,
    PRIMARY KEY (title, tag)
);
CREATE INDEX IF NOT EXISTS idx_tags_tag ON tags (tag);

-- 앞머리 값. `status: active` 처럼 **사람이(또는 남의 볼트가) 적은 것**을 그대로 담는다.
-- 옵시디언 볼트를 들이니 `status` 가 101장, `source` 가 97장이었는데 **그 값으로 찾을 길이
-- 없었다** — `status:active` 가 83장을 두고 2장을 내놓았다(모르는 이름은 낱말로 쳤다).
CREATE TABLE IF NOT EXISTS props (
    title TEXT NOT NULL,
    key   TEXT NOT NULL,
    value TEXT NOT NULL,
    PRIMARY KEY (title, key)
);
CREATE INDEX IF NOT EXISTS idx_props_key ON props (key, value);

-- 별칭. 다른 이름으로도 [[링크]]가 닿는다. 별칭은 온 저장소에서 하나뿐이다.
CREATE TABLE IF NOT EXISTS aliases (
    alias TEXT PRIMARY KEY,
    title TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_aliases_title ON aliases (title);
"""

# 낱말 색인. `LIKE '%낱말%'`은 "voice 튜닝"처럼 **떨어져 있는 두 낱말**을 못 찾고,
# 20년치에서는 훑는 값도 감당이 안 된다. FTS5는 SQLite에 들어 있어 새 짐이 없다.
# `unicode61`은 한글을 낱말로 끊고, 뒤에 붙는 조사는 앞자리 맞추기(`저장*`)로 걸린다.
SEARCH_SCHEMA = """
CREATE VIRTUAL TABLE IF NOT EXISTS search USING fts5(
    path UNINDEXED, title, body, tokenize='unicode61 remove_diacritics 2');
"""

TASK_LINE_RE = re.compile(r"(?m)^(\s*[-*+] )\[([ xX])\]")


def flip_task(body: str, nth: int) -> tuple[str, bool] | None:
    """원문에서 `nth`번째 할 일 표를 뒤집는다. 없으면 None.

    보이는 글이 아니라 **원문을 고친다.** 파일이 원본이라 여기서 안 바꾸면 아무 일도
    안 일어난 것이다. 돌려주는 두 번째 값은 뒤집은 뒤의 상태(True = 한 일).
    """
    hits = list(TASK_LINE_RE.finditer(body))
    if not 0 <= nth < len(hits):
        return None
    m = hits[nth]
    now = m.group(2).lower() != "x"
    return body[:m.start()] + m.group(1) + ("[x]" if now else "[ ]") + body[m.end():], now


HEAD_RE = re.compile(r"(?m)^(#{1,6})\s+(.+?)\s*#*$")


def headings(body: str) -> list[tuple[int, str]]:
    """소제목 목록. `(깊이, 글자)`.

    18만 자짜리 기록에서 원하는 자리로 갈 길이 스크롤뿐이면 안 열게 된다.
    코드 덩어리 안의 `#`은 소제목이 아니다 — 파이썬 주석이 전부 목차에 뜬다.
    """
    out, fenced = [], False
    for line in body.splitlines():
        if line.lstrip().startswith(("```", "~~~")):
            fenced = not fenced
            continue
        if fenced:
            continue
        m = HEAD_RE.match(line)
        if m:
            out.append((len(m.group(1)), m.group(2).strip()))
    return out


def 물음낱말(물음: str) -> list[str]:
    """물음에서 **찾을 만한 낱말**을 뽑는다. 긴 것부터.

    ★★ **한국어는 조사가 붙어서 글자 그대로는 거의 안 맞는다.** 물음은 「예산을」인데
    본문은 「예산은」이라 `in` 이 거짓이다. 그래서 세 글자 이상인 낱말은 **끝 한 글자를
    뗀 것도** 같이 준다 — 조사는 대개 한 글자다(은·는·이·가·을·를·의·에·도).
    형태소 분석기를 들이지 않는 이유: 사전과 짐이 늘고, 여기서 필요한 것은 그만큼이 아니다.

    한 곳에서 정한다 — 요약 고르기(AI 1단)와 발췌(사람 화면)가 **같은 규칙**을 써야
    「화면에는 보이는데 AI 는 못 본다」가 안 생긴다.
    """
    out: list[str] = []
    for w in re.split(r"[^0-9A-Za-z가-힣]+", 물음 or ""):
        if len(w) >= 2:
            out.append(w)
            if len(w) >= 3:
                out.append(w[:-1])      # 조사 한 글자를 뗀 것
    # 긴 것이 더 또렷하다. 같은 길이면 먼저 나온 것.
    return sorted(dict.fromkeys(out), key=len, reverse=True)


def 요약(body: str, extra: dict | None = None, 길이: int = 120,
       물음: str = "") -> str:
    """한 줄로 무슨 글인지 밝힌다. **물음을 주면 그 물음에 걸린 줄**을 고른다.

    ★★ **꺼내기 1단에 쓰는 것이다.** 찾은 글의 몸을 통째로 주면 여덟 장에
    **46,000자(≈ 18,000토큰)** 이 나가는데(재 본 값: 평균 5,814자 · 최대 184,467자),
    그중 실제로 읽는 것은 몇 줄이다. 1단은 **무엇이 있는지**만 보이고,
    고른 구획만 2단에서 펼친다.

    ★★ **`물음` 을 받는 까닭 — 같은 글자로 더 알려 준다.** 첫 문장만 주면 AI 는
    「이 글이 내 물음에 답하나」를 못 가려서 **2단을 여러 번 부른다**(그게 값이다).
    물음의 말이 든 줄을 대신 주면 **글자 수는 그대로인데** 고를 수 있게 된다.
    못 찾으면 예전처럼 첫 문장으로 내려간다 — 나빠지는 자리가 없다.
    """
    # ★ **자른 것은 잘랐다고 말한다.** 120자에서 그냥 끊으면 「베낄 것이」·「GGUF 파일을」
    #   처럼 문장 가운데서 멎는데, 읽는 쪽은 그게 끝인지 잘린 것인지 모른다 —
    #   AI 는 그 한 글자를 확인하려고 2단(900~1500자)을 부른다. 점 하나가 그것을 막는다.
    def 자르기(글: str) -> str:
        글 = 글.strip()
        return 글 if len(글) <= 길이 else 글[:길이] + "…"

    for 열쇠 in ("요약", "summary", "description", "설명"):
        값 = (extra or {}).get(열쇠)
        if isinstance(값, str) and 값.strip():
            return 자르기(값)
    줄들, 첫줄 = [], ""
    담 = False
    for 줄 in body.splitlines():
        굳 = 줄.strip()
        if 굳.startswith(("```", "~~~")):
            담 = not 담
            continue
        # 앞머리·소제목·줄자는 「무슨 글인가」에 답하지 않는다.
        if 담 or not 굳 or 굳.startswith(("#", "---", "===", ">", "|")):
            continue
        굳 = re.sub(r"[*`~\[\]]", "", 굳)
        if not 첫줄:
            첫줄 = 굳
        줄들.append(굳)
    if 물음 and 줄들:
        # 물음의 **두 글자 이상 낱말**이 몇 개나 든 줄인가. 가장 많이 든 줄을 준다.
        낱말 = 물음낱말(물음)
        if 낱말:
            점수 = [(sum(1 for w in 낱말 if w in 줄), -i, 줄)
                    for i, 줄 in enumerate(줄들)]
            맞은, _, 고른 = max(점수)
            if 맞은:
                return 자르기(고른)
    return 자르기(첫줄)


def 둘레(body: str, 물음: str, 폭: int = 400) -> tuple[str, bool]:
    """물음이 걸린 자리 **둘레만** 잘라 온다. `(글, 잘랐나)`.

    ★★ **긴 글은 소제목이 없으면 통째로 나간다.** 오너 창고에서 1000자 넘는 글이
    199장인데(평균 1301자) 그중 소제목이 있는 것은 **7장뿐**이다 — `heading=` 으로
    토막을 고르는 길이 사실상 없다. AI 가 필요한 건 몇 줄인데 1301자를 태운다.

    ★ **넉넉히 준다.** 아껴서 답을 자르면 AI 가 통째로 다시 부르므로 되레 손해다.
      못 찾으면 앞부분을 준다 — 그때도 「잘랐다」고 말한다.
    """
    if not 물음 or len(body) <= 폭 * 2:
        return body, False
    낮 = body.lower()
    at = -1
    for 말 in 물음낱말(물음):
        at = 낮.find(말.lower())
        if at >= 0:
            break
    if at < 0:
        return body[:폭 * 2], True
    start = max(0, at - 폭 // 2)
    end = min(len(body), at + 폭 * 2)
    # 줄 가운데서 자르지 않는다 — 읽는 쪽이 문장을 잃는다.
    if start:
        줄바꿈 = body.rfind(chr(10), 0, start)
        start = 줄바꿈 + 1 if 줄바꿈 >= 0 else start
    if end < len(body):
        줄바꿈 = body.find(chr(10), end)
        end = 줄바꿈 if 줄바꿈 >= 0 else end
    return body[start:end], (start > 0 or end < len(body))


def parse_links(body: str) -> list[tuple[str, str]]:
    """본문에서 (대상, 소제목)을 뽑는다. 보이는 글자는 연결과 무관해서 버린다.

    첨부(`![[사진.png]]`)는 뺀다 — 항목이 아니라 파일이다.
    """
    # ponytail: 경로 구분자(/ \)는 안 바꾼다 — 「A/B」 제목으로 건 링크는 resolve 가 잡지만
    #   역링크 목록에서는 빠진다. 그런 제목이 흔해지면 링크 표에 맞춘 꼴을 따로 둔다.
    return [(_링크맞춤(m.group(1).strip()), (m.group(2) or "").strip())
            for m in LINK_RE.finditer(body)
            if m.group(1).strip() and not is_attachment(m.group(1).strip())]


def _링크맞춤(이름: str) -> str:
    return unicodedata.normalize("NFC", 이름).translate(
        {k: v for k, v in _전각.items() if chr(k) not in "/\\"})


def parse_attachments(body: str) -> list[str]:
    """본문이 끼운 첨부 파일 이름들."""
    seen = []
    for m in EMBED_RE.finditer(body):
        name = m.group(1).strip()
        if is_attachment(name) and name not in seen:
            seen.append(name)
    return seen


def parse_embeds(body: str) -> list[tuple[str, str]]:
    """본문에서 (끼울 항목, 소제목)을 뽑는다. 첨부는 뺀다 — 그건 파일이지 항목이 아니다."""
    return [(m.group(1).strip(), (m.group(2) or "").strip())
            for m in EMBED_RE.finditer(body)
            if m.group(1).strip() and not is_attachment(m.group(1).strip())]


# 줄 끝에 달린 블록 이름. 옵시디언이 `[[글#^a1b2c3]]` 으로 한 **줄·문단**을 가리키는 길이다.
# 소제목이 없는 긴 글에서 딱 한 자리를 가리킬 수 있는 유일한 수단이라 우리에게도 값이 크다
# — 꺼내기 2단이 푸는 문제(1300자 중 필요한 건 몇 줄)를 사람 쪽에서 푸는 것과 같다.
# 이름에 한글을 받는다 — 옵시디언은 영숫자만 받지만 이 창고는 한글로 적힌다.
# 앞에 빈칸이 있어야 한다: 글 가운데의 `^` (거듭제곱·코드)를 블록 이름으로 읽으면 안 된다.
BLOCK_RE = re.compile(r"(?:(?<=\s)|^)\^([\w-]{1,64})[ 	]*$")


def block(body: str, bid: str) -> str:
    """`^이름` 이 달린 **한 덩이**를 잘라 온다. 없으면 빈 글.

    덩이는 그 줄부터 위로 **빈 줄까지**다 — 옵시디언이 문단 끝에 이름을 달기 때문이다.
    목록 줄에 달렸으면 그 줄 하나만 준다(위 항목까지 끌어오면 딴 말이 섞인다).
    이름 자체(`^이름`)는 떼고 준다 — 읽는 쪽에 쓸모가 없다.
    """
    want = bid.strip().lstrip("^").lower()
    if not want:
        return ""
    줄들 = body.splitlines()
    for i, 줄 in enumerate(줄들):
        m = BLOCK_RE.search(줄)
        if not m or m.group(1).lower() != want:
            continue
        끝 = 줄[:m.start()].rstrip()
        if 끝.lstrip().startswith(("-", "*", "+")) or re.match(r"\s*\d+[.)]", 끝):
            return 끝.strip()          # 목록 한 줄
        모음 = [끝] if 끝 else []
        j = i - 1
        while j >= 0 and 줄들[j].strip():
            모음.insert(0, 줄들[j])
            j -= 1
        return chr(10).join(모음).strip()
    return ""


def blocks(body: str) -> list[str]:
    """이 글에 달린 블록 이름들. 없는 이름을 물었을 때 **있는 것을 보여 주려고** 쓴다."""
    out = []
    for 줄 in body.splitlines():
        m = BLOCK_RE.search(줄)
        if m:
            out.append(m.group(1))
    return out


def section(body: str, heading: str) -> str:
    """소제목 아래 한 토막만 잘라 온다.

    `![[보고서#8월 정산]]`으로 부르면 보고서 전체가 아니라 그 자리만 보여야 한다.
    다음 소제목이 같거나 더 높은 층이면 거기서 끊는다 — 하위 소제목은 그 토막에 속한다.

    `#^이름` 은 소제목이 아니라 **블록**이다. 옵시디언과 같은 꼴이라 여기서 갈라 보낸다
    — 부르는 쪽(화면 끼워넣기 · 꺼내기 2단)을 안 고쳐도 둘 다 되게 하려는 것이다.
    """
    if heading.strip().startswith("^"):
        return block(body, heading)
    want = heading.strip().lower()
    lines = body.splitlines()
    depth, out, on = 0, [], False
    for line in lines:
        bare = line.lstrip()
        if bare.startswith("#"):
            level = len(bare) - len(bare.lstrip("#"))
            title = bare.lstrip("#").strip().lower()
            if on and level <= depth:
                break
            if not on and title == want:
                on, depth = True, level
                continue
        if on:
            out.append(line)
    return chr(10).join(out).strip()


def parse_tags(body: str) -> list[str]:
    """본문에서 #태그를 뽑는다.

    걸러야 할 것 셋: **줄 첫머리의 #은 마크다운 제목**이고, `[[노트#소제목]]`의 #은
    링크의 일부이며, 코드 블록 안의 #은 코드다. 안 거르면 문서마다 엉뚱한 태그가 붙는다.
    """
    text = CODE_RE.sub(" ", body)
    text = LINK_RE.sub(" ", text)                       # 링크 안의 #은 소제목이다
    lines = [re.sub(r"^\s*#+\s", " ", ln) for ln in text.splitlines()]
    found = []
    for line in lines:
        for m in TAG_RE.finditer(line):
            tag = 태그인가(m.group(1))
            if tag and tag not in found:
                found.append(tag)
    return found


def 태그인가(글: str) -> str:
    """태그면 다듬은 이름, 아니면 빈 글.

    ★ **색상 코드는 태그가 아니다.** 실제 기록을 넣어 보니 `#0E1116`·`#3D6BFF` 가
    태그로 잡혀 태그 목록이 색깔로 뒤덮였다.

    ★★ **한 자리에 둔다.** 뽑는 쪽만 거르고 **칠하는 쪽은 안 걸러서**, 목록에는
    안 들어가는 색상 코드가 본문에서는 태그와 같은 붉은색으로 칠해졌다
    (시험 쪽 「뽑기와 색칠이 따로 논다」). 같은 판단을 두 군데서 하면 갈라진다.
    """
    tag = 글.strip("/-")
    if not tag or tag.isdigit() or HEX_COLOR.fullmatch(tag):
        return ""
    return tag


# 항목마다 자물쇠 하나. 서버(AI)와 화면이 한 프로그램 안에서 같은 파일을 쓰므로,
# 여기서 한 줄로 세우면 자기들끼리 부딪히는 일은 없어진다. 밖(옵시디언)은 못 세우지만
# 그쪽도 자리 바꾸기로 저장한다.
_LOCKS: dict[str, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()


def _lock_for(path: Path) -> threading.Lock:
    key = str(path).lower()
    with _LOCKS_GUARD:
        lock = _LOCKS.get(key)
        if lock is None:
            lock = _LOCKS[key] = threading.Lock()
    return lock


class WriteBlocked(OSError):
    """파일이 잠겨 못 썼다. 글은 옆에 `(못 쓴 글)` 로 남겨 뒀다."""


def _해시(글: str) -> str:
    """글의 지문. **mtime 이 아니라 글자를 본다** — SMB 볼트에서 mtime 은 초 단위
    해상도·시계 어긋남·캐싱으로 자주 틀린다. 글자는 안 틀린다."""
    import hashlib

    return hashlib.sha256(글.encode("utf-8", "replace")).hexdigest()[:32]


_잡은글잠금 = threading.local()
_이름바꾸기잠금 = threading.Lock()   # ponytail: 프로그램 전체에 하나. 창고가 여럿 떠 느려지면 창고마다로


class _덧붙이기잠금:
    """읽고 → 붙이고 → 쓰는 동안 **한 프로그램 안(실)과 프로그램 사이(창·서버)를 같이** 잠근다.

    ★★ 덧붙이기가 잠그지 않아, 같은 글에 동시에 덧붙이면 **80줄 중 40줄이 조용히 사라졌다**(재 봤다:
    한 프로그램 두 실 40/80, 두 프로그램 41/80). 둘 다 옛 몸을 읽고 제 줄만 붙여 덮었기 때문이다.
    AI(서버)와 사람(창)이 같은 기록에 쌓는 물건이라 흔한 일이다. 잠금 파일은 기록 폴더 곁(`vc-잠금`)에 둔다
    — 글 폴더에 두면 옵시디언에 보인다.
    """

    def __init__(self, 자리폴더: Path, 열쇠: str) -> None:
        자리폴더.mkdir(parents=True, exist_ok=True)
        이름 = hashlib.sha256(열쇠.encode("utf-8")).hexdigest()[:24]
        self.파일 = 자리폴더 / f"{이름}.lock"
        self.실잠금 = _lock_for(self.파일)
        self.손잡이 = None
        self.겹침 = False

    def __enter__(self):
        # ★ 같은 실이 이미 쥐고 있으면 그냥 지나간다. 읽고-고치고-쓰기를 감싼 채 `append` 를 부르면
        #   실잠금에서 영영 멈추거나(Lock 은 겹쳐 못 잡는다) 파일 잠금에서 15초를 헛돈다.
        잡은 = _잡은글잠금.__dict__.setdefault("파일", set())
        if self.파일 in 잡은:
            self.겹침 = True
            return self
        self.실잠금.acquire()
        잡은.add(self.파일)
        try:
            self.손잡이 = open(self.파일, "a+b")
            끝 = time.monotonic() + 15
            while True:
                try:
                    if os.name == "nt":
                        import msvcrt

                        self.손잡이.seek(0)
                        msvcrt.locking(self.손잡이.fileno(), msvcrt.LK_NBLCK, 1)
                    else:
                        import fcntl

                        fcntl.flock(self.손잡이.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    return self
                except OSError:
                    if time.monotonic() > 끝:
                        return self          # ponytail: 15초 넘게 못 잡으면 잠금 없이 간다(안 멈추는 쪽)
                    time.sleep(0.01)
        except OSError:
            return self                      # 잠금 파일조차 못 열면 잠금 없이 간다
        return self

    def __exit__(self, *_):
        if self.겹침:
            return
        try:
            if self.손잡이 is not None:
                try:
                    if os.name == "nt":
                        import msvcrt

                        self.손잡이.seek(0)
                        msvcrt.locking(self.손잡이.fileno(), msvcrt.LK_UNLCK, 1)
                    else:
                        import fcntl

                        fcntl.flock(self.손잡이.fileno(), fcntl.LOCK_UN)
                except OSError:
                    pass
                self.손잡이.close()
        finally:
            _잡은글잠금.파일.discard(self.파일)
            self.실잠금.release()


def _덮거나곁에(path: Path, text: str) -> None:
    """임시 파일 길이 막혔을 때 **마지막으로** 해 보는 것.

    그냥 덮어써 본다 — 남이 잠깐 반쪽을 보는 것보다 글이 통째로 사라지는 쪽이 나쁘다.
    그것마저 막히면 글을 버리지 않고 **곁에 남기고** `WriteBlocked` 를 올린다.
    부르는 쪽(화면)이 그걸 받아 「못 썼어」 라고 말한다.
    """
    try:
        path.write_text(text, encoding="utf-8")
    except OSError:
        # 잠긴 파일이다. 글을 버리지 않고 곁에 둔다 — 이름으로 무슨 일인지 보인다.
        beside = path.with_name(f"{path.stem}(못 쓴 글){path.suffix}")
        try:
            beside.write_text(text, encoding="utf-8")
        except OSError:
            pass   # 폴더째 잠겼다. 여기서 더 할 수 있는 게 없다
        raise WriteBlocked(str(path))


def _atomic_write(path: Path, text: str) -> None:
    """옆에 다 쓴 뒤 자리를 바꾼다. 통째로 덮어쓰면 **읽는 쪽이 반쪽을 본다.**

    쓰는 주체가 셋이다 — 화면, AI, 사람(옵시디언). 긴 글에서 실제로 깨졌다(20만 자에서
    2.5초 만에 재현). `os.replace`는 한 번에 바뀌므로 읽는 쪽은 옛 파일 아니면 새
    파일만 본다. 중간은 없다.

    윈도우 두 가지를 같이 막는다:

    - **임시 이름이 겹치면 안 된다.** 둘이 같은 항목을 동시에 쓰면 서로의 임시 파일을
      덮어써서 둘 다 실패한다. 실측에서 그렇게 터졌다.
    - **남이 열고 있으면 자리 바꾸기가 거부된다**(WinError 32). 읽는 건 순식간이라
      잠깐 기다렸다 다시 하면 대개 통과한다.

    끝까지 안 되면 **그냥 덮어쓴다.** 남이 잠깐 반쪽을 보는 것보다 AI가 쓴 글이
    통째로 사라지는 쪽이 훨씬 나쁘다.

    그것마저 막히면(사람이 읽기 전용으로 잠가 둔 파일) **터지지 않고 곁에 남긴다.**
    프로그램이 죽으면 쓰던 글이 사라지지만, 곁에 남기면 사람이 찾아 쓸 수 있다.
    """
    with _lock_for(path):
        tmp = path.with_name(f"{path.name}.{os.getpid()}-{threading.get_ident()}.tmp")
        try:
            tmp.write_text(text, encoding="utf-8")
        except OSError:
            # ★★ **폴더째 잠기면 임시 파일부터 못 만든다.** 맥·리눅스의 자리 바꾸기는
            #   파일 권한이 아니라 **폴더** 권한만 본다 — 그래서 윈도우처럼
            #   `os.replace` 에서 걸리지 않고 여기서 먼저 걸린다. 이 자리가 안 막혀
            #   있어서 맥에서는 `PermissionError` 가 그대로 위로 올라갔고,
            #   **화면은 「못 썼어」 를 한마디도 못 했다**(자체점검이 그걸 잡았다).
            _덮거나곁에(path, text)
            return
        for wait in (0, 0.01, 0.02, 0.05, 0.1, 0.2, 0.4):
            if wait:
                time.sleep(wait)
            try:
                os.replace(tmp, path)
                return
            except PermissionError:
                continue
        try:
            _덮거나곁에(path, text)
        finally:
            tmp.unlink(missing_ok=True)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


# 파일 이름에 못 쓰는 글자를 **모양이 같은 전각 글자**로 바꾼다. 옵시디언은 이 글자들을 제목에서
# 아예 막는다. 우리는 막지 않고 바꾼다 — AI 는 「질문? 답」 같은 제목을 흔히 짓는다.
_전각 = str.maketrans({"?": "？", ":": "：", "/": "／", "\\": "＼", "|": "｜",
                      "*": "＊", '"': "＂", "<": "＜", ">": "＞"})


def _알림(말: str) -> None:
    """콘솔에 찍고 **기록 파일(vc-기록.log)에도** 남긴다.

    ★ 구운 판은 콘솔이 없어(`--noconsole`) `print` 가 조용히 사라진다 — 색인을 깨짐으로 옆에 치웠다,
    벡터를 통째로 버렸다 같은 알림을 **아무도 못 봤다.** `report` 는 여기서 늦게 불러 순환을 피한다.
    """
    print(말)
    try:
        import report

        report.trail(말)
    except Exception:
        pass


def 훑어내림(뿌리, 끝: tuple[str, ...] | None = None, 폴더도: bool = False):
    """뿌리 아래를 **안전하게** 내려간다. 연결 폴더(심볼릭·정션)와 점 폴더에는 안 들어간다.

    ★★ `rglob` 은 정션을 따라간다. 볼트 안에 볼트 자신을 가리키는 정션이 있으면 끝없이 들어가
    경로가 너무 길어져 터졌다 — 켤 때 `*.tmp` 치우기·첨부 찾기·화면 폴더 지켜보기·흡수가 다
    `rglob` 이라 **켜기 자체가 매달릴 수 있었다.** 이 한 자리로 모은다.
    `끝` 을 주면 그 확장자 파일만(소문자로 견준다), `폴더도` 면 폴더도 내준다.
    """
    import stat as _stat

    def 연결인가(자리: str) -> bool:
        try:
            st = os.lstat(자리)
        except OSError:
            return True
        return _stat.S_ISLNK(st.st_mode) or bool(getattr(st, "st_file_attributes", 0) & 0x400)

    # ★★ **윈도우는 260자 넘는 경로를 조용히 못 연다**(긴 경로 설정이 꺼진 PC 가 흔하다). 깊은 폴더의
    #   글이 훑기에서 **말없이 빠졌다**(재 봤다: 325자 경로의 글이 색인 0). 윈도우에서는 `\?\` 접두로
    #   내려가고, 내줄 때는 **짧은 경로는 접두를 떼서** 준다 — 색인 열쇠가 예전과 같아야 「사라짐+새로 생김」이
    #   안 난다. 긴 경로만 접두가 붙은 채로 나가고, 그 꼴은 매번 같다(길이로 정해진다).
    B = chr(92)
    긴앞 = B + B + "?" + B
    뿌리글 = os.path.abspath(str(뿌리))
    if os.name == "nt" and not 뿌리글.startswith(긴앞) and not 뿌리글.startswith(B + B):
        뿌리글 = 긴앞 + 뿌리글

    def 내줄꼴(자리: str) -> Path:
        if 자리.startswith(긴앞) and len(자리) - len(긴앞) < 250:
            return Path(자리[len(긴앞):])
        return Path(자리)

    for 위, 폴더들, 파일들 in os.walk(뿌리글, followlinks=False, onerror=lambda e: None):
        폴더들[:] = [d for d in 폴더들 if not d.startswith(".") and not 연결인가(os.path.join(위, d))]
        if 폴더도:
            for d in 폴더들:
                yield 내줄꼴(os.path.join(위, d))
        for 이름 in 파일들:
            if 끝 is None or 이름.lower().endswith(끝):
                yield 내줄꼴(os.path.join(위, 이름))


def 제목맞춤(title: str) -> str:
    """제목을 **한 꼴**로 모은다 — NFC(맥 한글) + 파일에 못 쓰는 글자는 전각으로.

    ★★ 전에는 못 쓰는 글자를 `-` 로 바꿨다. 그러자 ① 「질문? 답」이 「질문- 답」으로 저장돼
    **`[[질문? 답]]` 링크가 끊겼고** ② 「질문? 답」과 「질문: 답」이 **같은 파일로 서로 덮였다.**
    전각은 뜻이 그대로 보이고 서로 안 겹친다. 제목을 받는 모든 자리가 이것을 거친다.
    """
    return unicodedata.normalize("NFC", title).translate(_전각)


def safe_title(title: str) -> str:
    """제목을 파일명으로 쓴다. 옵시디언에서 [[제목]]으로 이어지려면 이름이 곧 식별자다.

    ★★ **자를 때 앞부분이 같으면 한 글이 다른 글을 조용히 덮는다.** 재 봤다:
    `'길'*300 + 'A'` 와 `'길'*300 + 'B'` 를 쓰면 둘 다 같은 파일이 되어 **먼저 것이 사라진다**
    (A 를 읽으면 B 의 몸이 나왔다). 아무 말도 안 나오는 종류라 더 나쁘다.
    그래서 **자를 때만** 제목 지문 여섯 자를 꼬리로 붙인다 — 안 자르는 제목은 그대로다
    (기존 파일 이름이 바뀌면 옵시디언 링크가 끊긴다).
    """
    cleaned = UNSAFE.sub("-", 제목맞춤(title)).strip().strip(".")
    if len(cleaned) > 80:
        지문 = hashlib.sha256(title.encode("utf-8")).hexdigest()[:6]
        return cleaned[:73].rstrip() + "~" + 지문
    return cleaned or "무제"


@dataclass
class Note:
    title: str
    body: str
    kind: str = "note"
    pinned: bool = False
    id: str = ""
    created: str = ""
    declaration: dict | None = None  # 스킬 선언문(결정 17). 일반 항목은 비어 있다.
    # 다른 이름으로도 [[링크]]가 닿게 한다. "회사"를 "직장"으로도 부르는 식이다.
    aliases: list[str] = field(default_factory=list)
    # 사람이 손댄 항목인지. 평소에는 AI가 쌓지만, 사람이 틀린 걸 고쳤다면 그 손질이
    # 나중 관찰에 밀리면 안 된다(결정 22와 같은 원칙).
    edited_by: str = ""
    # 우리가 모르는 프론트매터는 **그대로 지고 다닌다.** 옵시디언 볼트에는 `type`·
    # `date`·`status`·`source` 같은 제 나름의 항목이 있는데, 모른다고 버리면
    # 우리 프로그램으로 한 번 저장할 때마다 그것들이 조용히 사라진다.
    extra: dict = field(default_factory=dict)

    def links(self) -> list[tuple[str, str]]:
        return parse_links(self.body)

    def tags(self) -> list[str]:
        """본문의 `#태그` **와** 앞머리 `tags:` 를 합친다.

        ★★ 옵시디언은 태그를 앞머리에도 적는다(`tags:` 아래 `- 할일`). 그것을 안 세면
        옵시디언에서 붙인 태그가 이 창고에서는 **없는 것**이 된다 — 같은 볼트를 두 도구가
        나눠 보는데 한쪽만 안 보이는 꼴이라, 사람은 태그가 사라졌다고 느낀다.
        """
        든것 = parse_tags(self.body)
        앞 = self.extra.get("tags") or self.extra.get("tag")
        if isinstance(앞, str):
            앞 = [조각.strip() for 조각 in 앞.replace(",", " ").split() if 조각.strip()]
        if isinstance(앞, list):
            for t in 앞:
                t = str(t).strip().lstrip("#")
                if t and t not in 든것:
                    든것.append(t)
        return 든것

    def embeds(self) -> list[tuple[str, str]]:
        return parse_embeds(self.body)

    def attachments(self) -> list[str]:
        return parse_attachments(self.body)

    #  우리가 쓰는 프론트매터 열쇠. 이 밖의 것은 `extra`로 넘어간다.
    OURS = ("id", "kind", "pinned", "created", "aliases", "edited_by", "declaration",
            "스키마")

    def 본문앞머리끌어올리기(self) -> bool:
        """본문 맨 앞에 사람이 적은 `---` 블록이 있으면 **진짜 앞머리로 올린다.**

        ★ 안 올리면 파일에 `---` 블록이 **두 겹**으로 쌓인다. 옵시디언은 **첫 블록만**
        속성으로 읽으므로, 사람이 적은 `type`·`date`·`status` 는 지워지진 않아도
        **속성으로서는 죽고 본문 글자가 된다** — 읽기 모드에서 제목처럼 굵게 뜨고,
        검색 미리보기 첫 줄을 통째로 차지해 무슨 글인지 안 보이게 만든다.

        ★★ **AI 에게 더 아프다.** 이 창고는 AI 의 바깥 기억이라 AI 가 `type:` 이나
        `status:` 로 걸러 회상하는데, 속성이 본문 글자면 **걸리지 않는다.**

        우리 열쇠(`OURS`)는 덮지 않는다 — 사람이 본문에 `id:` 를 적었다고 항목의
        신원이 바뀌면 안 된다. 값이 겹치면 우리 것이 이긴다.
        """
        m = FRONTMATTER_RE.match(self.body)
        if not m:
            return False
        속, 남은 = m.group(1), m.group(2)
        골라낸: dict[str, object] = {}
        for 줄 in 속.splitlines():
            줄 = 줄.rstrip()
            if not 줄.strip():
                continue
            열쇠, 나눔, 값 = 줄.partition(":")
            # `key: value` 꼴이 아니면 앞머리가 아니다 — 그냥 가로줄(`---`)로 둔다.
            if not 나눔 or not 열쇠.strip() or 열쇠 != 열쇠.lstrip():
                return False
            골라낸[열쇠.strip()] = _앞머리값(값.strip())
        if not 골라낸:
            return False
        for 열쇠, 값 in 골라낸.items():
            if 열쇠 not in self.OURS:      # 우리 신원은 사람 글이 못 덮는다
                self.extra[열쇠] = 값
        self.body = 남은.lstrip("\n")
        return True

    def dumps(self) -> str:
        # 남의 것을 먼저, 원래 순서대로. 그래야 옵시디언에서 열었을 때 낯설지 않다.
        front: dict[str, object] = dict(self.extra)
        front.update({
            "id": self.id,
            "kind": self.kind,
            "pinned": self.pinned,
            "created": self.created,
            # ★ **여기 한 자리에서 찍는다.** 부르는 쪽마다 맡기면 반드시 몇 군데가
            # 샌다 — 이 프로젝트에서 따옴표 감싸기가 네 군데, 태그 거르기가 두 군데
            # 갈라져 있었고 **한 자리로 모으고 나서야** 알았다. 한 군데라도 안 찍으면
            # 「필드가 없다 = 아직 안 옮겼다」가 조용히 거짓이 되고 적합률이 거짓말한다.
            "스키마": 적는판,
        })
        if self.aliases:
            front["aliases"] = self.aliases
        if self.edited_by:
            front["edited_by"] = self.edited_by
        if self.declaration is not None:
            # 한 줄 JSON이라 옵시디언에서 열어 그대로 고칠 수 있다.
            front["declaration"] = self.declaration
        # ★ 못 읽은 덩이는 **글자 그대로** 되돌려 쓴다. JSON 으로 감싸면 사람이 적은
        #   중첩 사전·여러 줄 글이 한 줄짜리 따옴표 글자로 뭉개진다.
        표시 = {k[:-3]: v for k, v in front.items() if k.endswith("~표시")}
        front = {k: v for k, v in front.items() if not k.endswith("~표시")}
        lines = [f"{k}: {표시[k]}" + chr(10) + v if isinstance(v, 원문그대로) and k in 표시
                 else f"{k}:" + chr(10) + v if isinstance(v, 원문그대로)
                 else f"{k}: {json.dumps(v, ensure_ascii=False)}"
                 for k, v in front.items()]
        return "---\n" + "\n".join(lines) + "\n---\n" + self.body.rstrip() + "\n"

    @classmethod
    def loads(cls, title: str, raw: str) -> Note:
        # ★★ **맥에서 온 한글은 조합형(NFD)이다.** 맥 파일 이름·글은 「ㅎ+ㅚ+ㅣ」처럼 풀어
        #   적혀서, 윈도우에서 친 「회의록」(NFC)과 **글자가 다르다** — 재 보니 그 글이 안 열리고
        #   `[[회의록]]` 링크가 파일이 있는데도 「아직 없는 것」으로 셌다. 오너의 맥이 오면
        #   같은 볼트를 두 기계가 나눠 쓴다. **읽는 첫 자리에서 NFC 로 모은다**
        #   (파일은 우리가 다시 쓸 때까지 그대로다).
        title = 제목맞춤(title)
        raw = unicodedata.normalize("NFC", raw)
        m = FRONTMATTER_RE.match(raw)
        if not m:
            # 사용자가 손으로 만든 파일. 그대로 받아들인다.
            return cls(title=title, body=raw, created=_now())
        front = _앞머리풀기(m.group(1))
        decl = front.get("declaration")
        alias = front.get("aliases")
        extra = {k: v for k, v in front.items() if k not in cls.OURS}
        if isinstance(alias, str):
            alias = [a.strip() for a in alias.split(",") if a.strip()]
        return cls(
            extra=extra,
            aliases=[str(a) for a in alias] if isinstance(alias, list) else [],
            edited_by=str(front.get("edited_by", "")),
            title=title,
            body=m.group(2),
            kind=str(front.get("kind", "note")),
            pinned=bool(front.get("pinned", False)),
            id=str(front.get("id", "")),
            created=str(front.get("created", _now())),
            declaration=decl if isinstance(decl, dict) else None,
        )


class Notes:
    def __init__(self, root: str | Path = "", index: str | Path = ":memory:",
                 index_now: bool = True) -> None:
        """`index_now=False`면 열기만 하고 훑지 않는다.

        생성자에서 통째로 훑으면 **항목이 많을수록 켜는 데만 몇 십 초**가 든다
        (2000개에 4.2초, 10만 개 환산 3분 반). 화면은 먼저 뜨고 훑기는 뒤에서 돌아야 한다.
        """
        # 기본 자리를 여기서 정한다. 부르는 쪽마다 정하게 두면 한 곳을 놓쳤을 때
        # 설치 폴더에 기록이 샌다.
        #
        # **반드시 절대 경로로 못 박는다.** 색인은 경로를 열쇠로 쓰는데, 같은 볼트를
        # `data/notes`로 한 번, 절대 경로로 한 번 열면 **다른 문자열**이 되어 매번
        # 100개가 "사라짐 + 새로 생김"으로 처리된다. 그러면 새로 넣은 링크를 뒤이어
        # 도는 정리 단계가 지워, 링크·태그가 조용히 0이 된다(실제로 그랬다).
        self.root = (Path(root) if root else paths.notes_dir()).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        for junk in 훑어내림(self.root, (".tmp",)):
            try:
                junk.unlink(missing_ok=True)  # 쓰다 죽으면 남는다. 항목으로 세면 안 된다
            except OSError:
                pass
        self.index_path = index      # 딴 실이 제 연결을 열 때 쓴다
        # ★★ **색인이 깨져 있으면 옆에 치우고 새로 만든다.** 색인은 `.md` 에서 언제든 다시 만드는
        #   파생물인데(저장소 규칙 4조), 전원이 나가 파일이 깨지면 `DatabaseError` 로 **프로그램이
        #   아예 안 켜졌다**(재 봤다: 앞머리 깨짐·반쯤 잘림 둘 다). 잠김 같은 일시 오류는 깨짐이 아니다.
        try:
            self._색인열기(index)
        except sqlite3.OperationalError:
            raise
        except sqlite3.DatabaseError as 깨짐:
            self._깨진색인치우기(index, 깨짐)
            self._색인열기(index)
        try:
            self.conn.executescript(SEARCH_SCHEMA)
            self.fts = True
        except sqlite3.OperationalError:
            # FTS5 없이 지은 파이썬. 느린 옛 길로 돌아가되 뜨기는 한다.
            self.fts = False
        self.conn.commit()
        self._heal_search()
        self._heal_vectors()
        self.write_rules()
        if index_now:
            self.reindex()

    def _is_history(self, path: Path) -> bool:
        """항목으로 세면 안 되는 자리. 지난 판과 서식은 글이지 항목이 아니다. VC 가 적는 기계 기록 요약도."""
        return HISTORY_DIR in path.parts or TEMPLATE_DIR in path.parts or VC_LOG_DIR in path.parts

    def _색인열기(self, index) -> None:
        """색인 파일을 열고 표 모양을 맞춘다. 깨졌으면 `sqlite3.DatabaseError` 가 난다."""
        self.conn = sqlite3.connect(index, check_same_thread=False, factory=paths.잠근연결)
        # WAL: 쓰는 놈 하나와 읽는 놈 여럿이 동시에 돈다. 기본(delete)에서는 쓰는 동안
        # 읽기가 통째로 막혀 "database is locked"가 난다 — AI와 사람이 같이 쓰는 구조다.
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA busy_timeout=8000")
        # 커밋마다 디스크에 못 박지 않는다. **색인은 파일에서 언제든 다시 만든다** —
        # 전원이 나가 마지막 몇 건이 날아가도 다시 훑으면 그만이다. 기본값에서는
        # 검색 한 번의 커밋이 1초를 먹었다(18만 자짜리 행을 다시 쓰면서 동기화).
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(INDEX_SCHEMA)
        # 벡터 표는 **다시 만들 수 있다.** 모양이 예전 것이면 버리고 새로 만든다 —
        # 조각마다 한 줄이던 것을 항목마다 한 줄로 바꿨다.
        # **여기 적힌 칸 이름이 곧 지금 모양이다.** 스키마에 칸을 늘리면 이 집합도
        # 같이 늘려야 한다 — 안 늘리면 `CREATE TABLE IF NOT EXISTS` 가 아무것도 안 해서
        # 쓰던 색인에 새 칸이 안 생기고, 읽으러 갔다가 통째로 죽는다.
        # 실제로 그렇게 냈다: `tvec` 을 더하고 이 줄을 안 고쳐, 이어 쓰는 사람은
        # 검색이 전부 죽었다(`no such column: v.tvec`).
        cols = {r[1] for r in self.conn.execute("PRAGMA table_info(vectors)")}
        if cols and cols != {"path", "vec", "tvec"}:
            self.conn.execute("DROP TABLE vectors")
            self.conn.execute("UPDATE notes SET vec_mtime = 0")
        self.conn.executescript(VECTOR_SCHEMA)
        # ★★ **새 표는 만들어져도 비어 있다.** `CREATE TABLE IF NOT EXISTS` 는 표만
        #   만들고 내용을 안 채운다 — 쓰던 색인에서는 `props` 가 텅 빈 채라
        #   `status:active` 가 **0장**을 내놓는다. 「되기는 되는데 아무것도 안 나온다」가
        #   제일 나쁜 꼴이다(같은 함정을 `links` 흐림 칸에서 이미 한 번 밟았다).
        #   글이 있는데 앞머리가 하나도 없으면 **한 번 다시 훑어 채운다.**
        self._앞머리이름 = None
        try:
            글있음 = self.conn.execute("SELECT 1 FROM notes LIMIT 1").fetchone() is not None
            앞머리있음 = self.conn.execute("SELECT 1 FROM props LIMIT 1").fetchone() is not None
            self._앞머리채울까 = bool(글있음 and not 앞머리있음)
        except sqlite3.Error:
            self._앞머리채울까 = False

        # 이미 쓰던 색인에는 이 칸이 없다. 색인은 다시 만들 수 있지만 2만 개를
        # 다시 훑게 하느니 칸 하나를 붙이는 게 싸다.
        # ★★ **칸을 더할 때는 반드시 여기에도 적는다.** `CREATE TABLE IF NOT EXISTS`
        # 는 **이미 있는 표를 안 고친다** — 새로 만든 색인에만 칸이 생기고, 쓰던
        # 색인에는 안 생긴다. 그러면 그 칸을 쓰는 자리가 통째로 터진다:
        # 실제로 「links 표에 흐림 칸이 없다」로 **새 글 쓰기가 죽었고**, 만든 쪽은
        # 기록을 새로 부어서(빈 색인) 못 봤다. **올려 쓰는 길을 안 밟은 것이다.**
        # **있는지 먼저 보고 없을 때만 붙인다.** 매번 던지고 받는 쪽으로 했더니
        # 색인을 열 때마다 예외가 셋씩 났고, 검사에서 죽는 일이 1/5 → 4/5 로 늘었다
        # (되돌려서 원래 값이 나오는지 다섯 번씩 재고 갈랐다).
        for 표, 칸, 꼴 in (("notes", "vec_mtime", "REAL NOT NULL DEFAULT 0"),
                          ("notes", "wrote", "TEXT NOT NULL DEFAULT ''"),
                          ("links", "흐림", "INTEGER NOT NULL DEFAULT 0")):
            있는칸 = {r[1] for r in self.conn.execute(f"PRAGMA table_info({표})")}
            if 있는칸 and 칸 not in 있는칸:
                self.conn.execute(f"ALTER TABLE {표} ADD COLUMN {칸} {꼴}")

    def _깨진색인치우기(self, index, 깨짐) -> None:
        """깨진 색인을 **지우지 않고 옆에 치운다**(무슨 일이 났는지 나중에 볼 수 있게)."""
        conn = getattr(self, "conn", None)
        if conn is not None:
            try:
                conn.close()           # 연 채로는 윈도우가 파일을 못 옮긴다
            except Exception:
                pass
        if str(index) == ":memory:":
            return
        때 = time.strftime("%Y%m%d-%H%M%S")
        for 곁 in ("", "-wal", "-shm"):
            자리 = Path(str(index) + 곁)
            if 자리.exists():
                try:
                    자리.replace(Path(f"{index}.깨짐-{때}{곁}"))
                except OSError:
                    pass
        _알림(f"[색인] 깨져서 옆에 치우고 새로 만든다: {Path(str(index)).name} "
              f"({type(깨짐).__name__}: {깨짐})")

    def notes_files(self):
        """항목 파일만. 지난 판은 항목이 아니다 — 세면 항목 수가 스무 배가 된다.

        ★★ **훑는 중에 폴더가 사라져도 멈추면 안 된다.** 밖에서 파일을 만지는 것이
        이 물건의 정상 쓰임이다 — 옵시디언·동기화 도구·사람 손. **한 폴더 때문에
        20년치가 안 보이면 안 된다.**

        ★★ **연결 폴더(정션·심볼릭 링크)는 따라가지 않는다.** 볼트 안에 볼트 자신을 가리키는
        정션이 있으면 `rglob` 이 끝없이 따라 들어가 경로가 너무 길어져 터졌고, 그 자리에서
        훑기가 멈춰 **뒤에 있는 글이 조용히 빠졌다**(재 봤다). 한 폴더씩 내려가며 연결 폴더·
        점 폴더(`.trash`·`.obsidian`·`.git`)·지난 판을 **들어가기 전에** 잘라 낸다.
        """
        for path in 훑어내림(self.root, (".md",)):
            if not self._is_history(path):
                yield path

    # --- 지난 판 -------------------------------------------------------

    def history_dir(self, path: Path) -> Path:
        """그 항목의 지난 판이 쌓이는 곳. 원래 폴더 구조를 그대로 따라간다."""
        try:
            rel = path.relative_to(self.root).parent
        except ValueError:
            rel = Path()
        return self.root / HISTORY_DIR / rel / path.stem

    def keep_history(self, path: Path, old: str, always: bool = False) -> None:
        """덮어쓰기 **전의** 글을 한 판 남긴다.

        치는 대로 저장하는 구조라 글자마다 남기면 금세 수천 판이 된다. 마지막 판이
        5분보다 최근이면 건너뛴다 — 되돌릴 만한 지점만 남는다.

        `always`는 그 묶음 규칙을 무시한다. **되돌리기가 그 자리다** — 방금 쓴 글을
        옛 판으로 덮는 것이라, 5분에 걸려 안 남으면 그 글은 어디에도 없다.
        확인창이 "다시 돌아올 수 있다"고 말해 놓고 못 돌아가면 그건 거짓말이다.
        """
        folder = self.history_dir(path)
        past = sorted(folder.glob("*.md")) if folder.exists() else []
        if not always and past and time.time() - past[-1].stat().st_mtime < HISTORY_GAP_SEC:
            return
        folder.mkdir(parents=True, exist_ok=True)
        # ★★ **이름이 겹치면 앞 판이 조용히 사라진다.** 초까지만 쓰다 겹쳐서 밀리초를
        #   넣었는데, **맥에서는 밀리초도 겹쳤다** — 빠른 기계에서는 두 번 쓰기가 같은
        #   1밀리초 안에 끝난다. 스무 번 재서 **아홉 번** 지난 판 하나가 덮여 없어졌다
        #   (자체점검이 「같은 내용은 안 남는다」에서 걸렸다).
        #   마이크로초까지 내리고, 그래도 겹치면 **빈 자리를 찾을 때까지** 민다.
        #   ※ 한 번 잰 시각으로 날짜와 아래 자릿수를 같이 만든다 — 따로 부르면
        #     그 사이에 초가 넘어가 엉뚱한 이름이 나올 수 있다.
        #   ※ 자릿수를 고정으로 둔다. 이름순이 곧 시간순이라, 길이가 들쑥날쑥하면
        #     가장 최근 판(`past[-1]`)을 잘못 고른다.
        지금 = time.time()
        while True:
            stamp = (time.strftime("%Y%m%d-%H%M%S", time.localtime(지금))
                     + f"-{int(지금 * 1_000_000) % 1_000_000:06d}")
            대상 = folder / f"{stamp}.md"
            if not 대상.exists():
                break
            지금 += 0.000001
        _atomic_write(대상, old)
        for gone in sorted(folder.glob("*.md"))[:-HISTORY_KEEP]:
            gone.unlink(missing_ok=True)

    def history(self, title: str) -> list[tuple[str, Path]]:
        """지난 판 목록. 최근이 먼저. `(언제, 파일)`."""
        folder = self.history_dir(self.path_of(title))
        if not folder.exists():
            return []
        out = []
        for f in sorted(folder.glob("*.md"), reverse=True):
            when = f.stem
            out.append((f"{when[:4]}-{when[4:6]}-{when[6:8]} {when[9:11]}:{when[11:13]}", f))
        return out

    # --- 고정 · 보관 · 색 · 휴지통 (편의 기능 18·27·28·30번) ---------------

    COLORS = ("빨강", "주황", "노랑", "초록", "파랑", "보라", "회색")

    def mark(self, title: str, pinned: bool | None = None, archived: bool | None = None,
             color: str | None = None) -> Note | None:
        """글 하나의 표시를 바꾼다. `None` 은 그대로. 색은 `""` 이면 지운다. 없는 글이면 None.

        보관·색은 앞머리(`보관: true` · `색: 노랑`)에 적는다 — 옵시디언에서도 속성으로 보인다.
        """
        with self._글잠금(title):
            note = self.read(title)
            if note is None:
                return None
            if pinned is not None:
                note.pinned = pinned
            if archived is not None:
                if archived:
                    note.extra["보관"] = True
                else:
                    note.extra.pop("보관", None)
            if color is not None:
                if color:
                    if color not in self.COLORS:
                        raise ValueError(f"모르는 색: {color}")
                    note.extra["색"] = color
                else:
                    note.extra.pop("색", None)
            self.write(note)
            return note

    def trashed(self) -> list[tuple[str, str, Path, Path]]:
        """휴지통 — 지난 판은 있는데 글이 없는 것. `(제목, 언제, 마지막 판, 되살릴 자리)` 새것이 먼저.

        지울 때 늘 한 판 남기므로(`_delete`) 휴지통을 따로 두지 않는다.
        """
        base = self.root / HISTORY_DIR
        out = []
        if not base.is_dir():
            return out
        for folder in {f.parent for f in base.rglob("*.md")}:
            rel = folder.relative_to(base)
            live = self.root / rel.parent / f"{folder.name}.md"
            if live.exists():
                continue
            판 = sorted(folder.glob("*.md"))[-1]
            when = 판.stem
            out.append((folder.name, f"{when[:4]}-{when[4:6]}-{when[6:8]} {when[9:11]}:{when[11:13]}", 판, live))
        return sorted(out, key=lambda x: x[1], reverse=True)

    def untrash(self, snapshot: Path) -> str | None:
        """휴지통에서 되살린다. 되살린 제목(없으면 None). 이력 폴더 밖의 파일은 안 받는다."""
        base = (self.root / HISTORY_DIR).resolve()
        snapshot = Path(snapshot).resolve()
        if base not in snapshot.parents or not snapshot.is_file():
            return None
        for title, _, 판, live in self.trashed():
            if 판.resolve() == snapshot:
                note = Note.loads(title, read_text(판))
                live.parent.mkdir(parents=True, exist_ok=True)
                self.write(note, at=live)
                return title
        return None

    def restore(self, title: str, snapshot: Path) -> bool:
        """지난 판으로 되돌린다.

        **되돌리기 전 글도 한 판 남는다** — `write`가 알아서 남기므로 여기서 또
        남기지 않는다. 되돌린 것이 잘못이었을 때 다시 돌아올 길이 있어야 한다.
        """
        path = self.path_of(title)
        if not snapshot.exists() or not path.exists():
            return False
        try:
            old = Note.loads(path.stem, read_text(snapshot))
        except (Vanished, OSError):
            return False      # 되돌릴 판이 사라졌다
        old.title = title
        # **되돌리기 직전 글을 반드시 한 판 남긴다.** 5분 묶음에 먹히면 그 글이
        # 파일에도 이력에도 없어진다 — 낯선 PC 에서 실제로 4줄이 사라졌다.
        # 남기기와 쓰기 사이에 덧붙인 줄은 이력에도 파일에도 없게 된다 — 한 잠금 안에서.
        with self._글잠금(title):
            try:
                self.keep_history(path, read_text(path), always=True)
            except Vanished:
                return False        # 되돌릴 글이 사라졌다
            except OSError as e:
                # ★★ 못 남기고 덮으면 **지금 글이 어디에도 없게 된다**(되돌리기가 그 자리다). 멈추고 알린다.
                _알림(f"[되돌리기 멈춤] 지금 글을 못 남겨 안 덮었다 — {type(e).__name__}")   # 글 이름은 안 적는다(묶음으로 나간다)
                raise WriteBlocked(str(path)) from e
            self.write(old)
        return True

    # --- 오늘 일지 · 서식 ------------------------------------------------

    def daily(self, day: str = "") -> Note:
        """오늘(또는 그날) 일지. 없으면 만든다.

        제목이 곧 날짜다(`2026-08-27`). 해마다 폴더가 갈리므로 20년이 쌓여도
        한 폴더에 몰리지 않는다.
        """
        day = day or time.strftime("%Y-%m-%d")
        # 없나 보고 만드는 사이 AI 가 오늘 일지에 먼저 쌓으면 서식이 그 줄을 덮는다 — 잠금 안에서.
        with self._글잠금(day):
            got = self.read(day)
            if got is not None:
                return got
            body = self.fill_slots(self.template("일지"), day) or f"# {day}" + chr(10)
            note = Note(title=day, body=body, kind="note")
            self.write(note)
            return note

    # 이 저장소를 만지는 모두(사람·AI·나중에 붙을 무엇이든)가 읽을 규칙. 항목으로는
    # 안 세는 자리(`_서식`)에 둔다.
    # 이 저장소를 만지는 모두(사람·AI·나중에 붙을 무엇이든)가 읽을 규칙. 항목으로는
    # 안 세는 자리(`_서식`)에 둔다.
    # ★★ **글을 여기 적지 않는다.** 층·갈래·앞머리·연산은 `wiki.py` 한 자리에 있고
    #   이 글은 거기서 **지어진다** — 두 군데 적으면 갈래를 더했을 때 갈라진다
    #   (오너 2026-09-20: 카파시 LLM Wiki 기준으로 창고를 새로 세운다).
    RULE_FILE = "이 창고를 쓰는 법.md"
    옛RULE_FILES = ("이 폴더를 만지는 규칙.md",)

    # 기본 서식(결정 19) — 받고 보낸 제품을 대충 적어도 틀이 잡히게. 폰 적기 탭에서도 고른다.
    DEFAULT_TEMPLATES = {
        "제품": ("# {{제목}}\n\n"
               "- 제품명 : \n"
               "- 종류 : \n"
               "- 받은날 : {{날짜}}\n"
               "- 보낸 곳(업체·담당) : \n"
               "- 보낸날 : \n"
               "- 상태 : 보유중\n\n"
               "## 사진\n\n"
               "## 메모\n"),
    }

    def write_rules(self) -> Path | None:
        """규칙 파일을 **한 번만** 만든다. 이미 있으면 안 건드린다.

        기본 서식은 **서식마다 한 번만** 넣는다. 넣은 이름을 `_서식/.기본서식넣음` 에 적어 두어
        ① 전부터 쓰던 창고에도 새 기본 서식이 한 번은 들어가고 ② 사람이 지우면 다시 안 생긴다.
        ★ 규칙 파일이 있을 때 건너뛰게 두었더니 **이미 쓰던 창고에는 「제품」이 영영 안 생겼다.**
        같은 이름 서식이 있으면 덮지 않는다.
        """
        where = self.template_root() / self.RULE_FILE
        try:
            where.parent.mkdir(parents=True, exist_ok=True)
            # ★ 옛 이름(`이 폴더를 만지는 규칙.md`)이 있으면 **새로 만들지 않는다.**
            #   사람이 고쳐 뒀을 수 있는 글을 같은 자리에 둘씩 늘리지 않는다.
            옛것 = any((self.template_root() / 옛).exists() for 옛 in self.옛RULE_FILES)
            if not where.exists() and not 옛것:
                _atomic_write(where, wiki.스키마글())
            표 = self.template_root() / ".기본서식넣음"
            넣은것 = set(read_text(표).split()) if 표.exists() else set()
            새로 = [이름 for 이름 in self.DEFAULT_TEMPLATES if 이름 not in 넣은것]
            for 이름 in 새로:
                틀 = self.template_root() / f"{이름}.md"
                if not 틀.exists():
                    _atomic_write(틀, self.DEFAULT_TEMPLATES[이름])
            if 새로:
                _atomic_write(표, chr(10).join(sorted(넣은것 | set(새로))) + chr(10))
        except (OSError, WriteBlocked, Vanished):
            return None      # 못 써도 프로그램이 멈출 이유가 없다
        return where

    def template_root(self) -> Path:
        return self.root / TEMPLATE_DIR

    def templates(self) -> list[str]:
        """쓸 수 있는 서식 이름들."""
        folder = self.template_root()
        if not folder.exists():
            return []
        try:
            # ★ 규칙 파일도 `_서식/` 에 산다 — 빼지 않으면 폰 서식 목록에 「이 폴더를 만지는 규칙」이 틀로 뜬다(5단계).
            return sorted(f.stem for f in folder.glob("*.md") if f.name != self.RULE_FILE)
        except OSError:
            return []

    def template(self, name: str) -> str:
        """서식 본문. 없으면 빈 글자."""
        f = self.template_root() / f"{safe_title(name)}.md"
        if not f.exists():
            return ""
        try:
            return Note.loads(f.stem, read_text(f)).body.strip()
        except (Vanished, OSError):
            return ""

    @staticmethod
    def fill_slots(text: str, title: str = "") -> str:
        """`{{날짜}}` 같은 자리를 채운다. 모르는 이름은 **그대로 둔다** — 지우면
        사용자가 오타를 냈을 때 흔적도 없이 사라진다."""
        if not text:
            return text
        now = time.localtime()
        table = {
            "날짜": time.strftime("%Y-%m-%d", now), "date": time.strftime("%Y-%m-%d", now),
            "시각": time.strftime("%H:%M", now), "time": time.strftime("%H:%M", now),
            "제목": title, "title": title,
        }
        return SLOT_RE.sub(lambda m: table.get(m.group(1).lower(), m.group(0)), text)

    # --- 뜻으로 찾기 ------------------------------------------------------

    def use_embedder(self, embed) -> None:
        """벡터를 만드는 함수를 끼운다. 안 끼우면 뜻 검색은 그냥 꺼져 있다.

        `notes`가 onnxruntime을 직접 물고 있으면, 모델이 없는 PC에서 항목 하나
        여는 것도 못 하게 된다. 재료는 밖에서 넣는다.

        ★ **모델이 바뀌었으면 여기서 옛 벡터를 버린다.** 예전에는 화면 쪽에서만
        크기를 맞춰 봐서, 명령줄로 재는 길(`--찾기점수`)에는 그 방어가 없었다 —
        구운 판(384)이 만든 벡터를 소스(e5-base 768)로 재다 `matmul` 에서 통째로
        터졌다. **부르는 쪽마다 맡기면 반드시 한 군데가 빠진다**(따옴표 네 군데·
        태그 두 군데와 같은 무늬). 재료가 들어오는 이 문 하나에서 본다.
        """
        self._embed = embed
        if embed is None:
            return
        try:
            width = len(_call_embed(embed, ["크기 재기"], "query: ")[0])
        except Exception as e:
            _알림(f"[뜻 벡터] 모델 폭을 못 재 뜻 검색을 끈다 — {type(e).__name__}: {e}")
            return        # 모델이 시원찮으면 뜻 검색만 꺼진다. 찾기는 살아야 한다
        # ★ **벡터를 통째로 버리면 말한다.** 모델 폭이 바뀌면 수천 장을 다시 만드는 몇 분짜리 일인데
        #   아무 표시가 없어, 그동안 뜻 검색이 약한 까닭을 알 길이 없었다.
        if self.drop_vectors_if_changed(width):
            self.벡터버림수 = getattr(self, "벡터버림수", 0) + 1
            _알림(f"[뜻 벡터] 모델 폭이 {width} 로 바뀌어 벡터를 통째로 다시 만든다")
        self._vec_cache = None

    def vec_left(self) -> int:
        """아직 벡터가 없는 항목 **수**. 목록을 끌어오지 않는다 — 진행 상황을 보여주려고
        2만 줄을 매번 다 가져오면 그것만으로 느려진다."""
        return self.conn.execute(
            "SELECT count(*) FROM notes WHERE vec_mtime != mtime").fetchone()[0]

    def vec_pending(self) -> list[str]:
        """아직 벡터가 없거나 낡은 항목들."""
        return [r["path"] for r in self.conn.execute(
            "SELECT path FROM notes WHERE vec_mtime != mtime ORDER BY used_at DESC NULLS LAST, mtime DESC")]

    def embed_one(self, path) -> bool:
        """**이 글 하나**의 벡터를 지금 만든다. 만들었으면 True.

        ★★ `embed_some` 은 `vec_pending` 차례대로 하는데, 그 차례의 **첫 키가
        `used_at DESC`** 다 — 검색으로 읽힌 글들이 앞선다. 그래서 방금 쓴 글을
        채우려고 `embed_some(1)` 을 불러도 **엉뚱한 글이 채워진다.**
        실제로 그랬다: 빈 창고에서는 됐는데(읽힌 글이 없어 mtime 차례였다) 실무 창고에서
        검색을 스무 번 돌린 뒤에는 안 됐다. **작은 창고가 우연히 통과시킨 자리다.**
        """
        낡 = self.conn.execute(
            "SELECT 1 FROM notes WHERE path = ? AND vec_mtime != mtime", (str(path),)).fetchone()
        if 낡 is None:
            return False
        옛것 = self.vec_pending
        try:
            self.vec_pending = lambda: [str(path)]      # 이 한 장만 만든다
            return self.embed_some(1) > 0
        finally:
            self.vec_pending = 옛것

    def embed_some(self, limit: int = 32) -> int:
        """벡터가 없는 항목을 조금씩 만든다. 2만 개면 8분짜리 일이라 뒤에서 돈다.

        돌려주는 값은 이번에 처리한 항목 수. 0이면 다 끝났다는 뜻이다.
        """
        embed = getattr(self, "_embed", None)
        if embed is None:
            return 0
        todo = self.vec_pending()[:limit]
        if not todo:
            return 0
        rows, blank = [], []
        for path in todo:
            got = self.conn.execute(
                "SELECT title, body, mtime FROM notes WHERE path = ?", (path,)).fetchone()
            if got is None:
                continue
            if not (got["body"] or "").strip():
                # **빈 항목은 뜻이 없다.** 그런데도 벡터를 만들어 두면 아무 물음에나
                # 어중간하게 가까워서 1등으로 올라온다 — 낯선 PC 에서 「새 항목 5」가
                # 「등이 결린다」의 1등이었다. 제목은 낱말 검색이 잡아 준다.
                blank.append((path, got["mtime"]))
                continue
            rows.append((path, meaning_card(got["title"], got["body"]),
                         got["mtime"], got["title"]))
        if blank:
            self.conn.executemany("DELETE FROM vectors WHERE path = ?",
                                  [(path,) for path, _ in blank])
            self.conn.executemany("UPDATE notes SET vec_mtime = ? WHERE path = ?",
                                  [(mtime, path) for path, mtime in blank])
        for at in range(0, len(rows), EMBED_BATCH):
            batch = rows[at:at + EMBED_BATCH]
            vecs = _call_embed(embed, [card for _, card, _, _ in batch], "passage: ")
            # **제목도 따로 한 벌.** 제목만으로 재면 순위가 눈에 띄게 나아지는데
            # (실측: 등수합 26 → 18), 본문에만 있는 말로 찾는 경우를 잃는다.
            # 그래서 둘 다 두고 **높은 쪽**을 쓴다. 제목은 짧아 값이 거의 안 든다.
            heads = _call_embed(embed, [title for _, _, _, title in batch], "passage: ")
            self.conn.executemany(
                "INSERT INTO vectors (path, vec, tvec) VALUES (?, ?, ?) "
                "ON CONFLICT(path) DO UPDATE SET vec = excluded.vec, tvec = excluded.tvec",
                [(path, _pack(v), _pack(h))
                 for (path, _, _, _), v, h in zip(batch, vecs, heads)])
            self.conn.executemany("UPDATE notes SET vec_mtime = ? WHERE path = ?",
                                  [(mtime, path) for path, _, mtime, _ in batch])
        self.conn.commit()
        self._vec_cache = None
        return len(todo)

    def _vectors(self):
        """벡터를 한 덩어리로 올려 둔다. 검색마다 다시 읽으면 2만 개에서 못 쓴다."""
        if getattr(self, "_vec_cache", None) is not None:
            return self._vec_cache
        try:
            import numpy as np
        except ImportError:
            return None
        try:
            rows = self.conn.execute(
                "SELECT n.title AS title, v.vec AS vec, v.tvec AS tvec FROM vectors v "
                "JOIN notes n ON n.path = v.path WHERE v.tvec IS NOT NULL").fetchall()
        except sqlite3.OperationalError:
            # **뜻 검색이 못 돌아도 낱말 검색은 살아야 한다.** 칸 하나가 어긋났다고
            # 찾기가 통째로 죽으면 사용자는 빠져나올 길이 없다 — 실제로 그렇게 냈다.
            return None
        if not rows:
            return None

        def 판(key):
            mat = np.frombuffer(b"".join(r[key] for r in rows), dtype="float16")
            # 셈은 float32로 한다 — 반정밀도로 곱하면 느리고 값도 흔들린다.
            mat = mat.reshape(len(rows), -1).astype("float32")
            # 미리 길이를 1로 맞춰 둔다 — 찾을 때마다 나누면 2만 번 나눗셈이다.
            norm = np.linalg.norm(mat, axis=1, keepdims=True)
            return mat / np.where(norm == 0, 1, norm)

        self._vec_cache = ([r["title"] for r in rows], 판("vec"), 판("tvec"))
        return self._vec_cache

    # 이보다 안 가까우면 안 붙인다. 자리가 남는다고 아무거나 채우면 **찾은 척**이 된다.
    NEAR_FLOOR = 0.35

    # 뜻 검색에서 제목 벡터를 뺄까. 재 볼 때만 켠다(기본은 끔 = 둘 다 쓴다).
    제목벡터끄기 = False

    def semantic(self, text: str, k: int = 8) -> list[tuple[str, float]]:
        """뜻이 가까운 항목들. `(제목, 가까움)`, 가까운 순."""
        embed = getattr(self, "_embed", None)
        if embed is None or not text.strip():
            return []
        # ★★ **낡은 벡터로 재면 조용히 틀린다.** 밖에서(옵시디언·메모장) 글을 고치면
        #   그 글의 벡터가 낡는데, 채우는 실은 30초마다 돈다. 그 사이에 물으면
        #   **고치기 전 뜻**으로 답한다 — 아무 표시도 없다. 실제로 그랬다: 밖에서
        #   「안개 속 등대가 …」를 넣고 바로 그 뜻으로 물으니 그 글이 안 나왔다.
        #   (오늘 잣대에서 낡은 벡터에 속아 곁실험 넷이 무너진 것과 같은 종류다.)
        #
        #   **몇 장 안 낡았으면 여기서 채운다**(한 장에 10ms 쯤). 많이 낡았으면
        #   그냥 둔다 — 첫 색인처럼 수천 장이 밀린 자리에서 검색을 붙들면 안 된다.
        #   문턱이 아니라 **k 와의 관계**로 정한다: 한 번에 보여 줄 수만큼만 따라잡는다.
        try:
            낡은수 = self.vec_left()
            if 0 < 낡은수 <= max(k, 8):
                while self.embed_some(8):
                    pass
        except Exception as e:
            _알림(f"[뜻 벡터] 찾기 전에 낡은 벡터를 못 채웠다 — {type(e).__name__}: {e}")   # 못 채워도 찾기는 돈다
        got = self._vectors()
        if got is None:
            return []
        import numpy as np

        titles, mat, heads = got
        (q,) = _call_embed(embed, [text], "query: ")
        q = np.asarray(q, dtype="float32")
        size = float(np.linalg.norm(q))
        if size == 0:
            return []
        q = q / size
        # **제목과 카드 중 가까운 쪽으로 친다.** 제목이 답일 때와 본문이 답일 때가
        # 다르고, 어느 쪽인지 미리 알 수 없다. 실측에서 이 방식이 둘 중 어느 하나만
        # 쓰는 것보다 나빴던 적이 없다.
        # ★ **제목 벡터를 끄고 재 볼 수 있게 해 둔다.** 이 최댓값이 실제로 답을
        # 덮는 자리가 나왔다 — 「프로그램이 을를 틀리게 붙이던 것」에서
        # **본문끼리는 「조사 어긋나감」이 이기는데**(0.7894 > 0.7856)
        # 엉뚱한 글의 **제목 벡터 0.8018** 이 그걸 덮어 1등을 가져갔다.
        # 기본은 그대로 둔다 — 「둘 중 하나만 쓰는 것보다 나빴던 적이 없다」는
        # 실측으로 정한 것이라, **바꾸려면 같은 잣대(스무 물음)로 다시 재야 한다.**
        # 그 재기를 할 수 있게 길만 낸다.
        near = mat @ q if self.제목벡터끄기 else np.maximum(mat @ q, heads @ q)
        out = []
        for i in np.argsort(-near)[:k]:
            score = float(near[int(i)])
            if score < self.NEAR_FLOOR:
                break          # 가까운 순이라 여기부터는 다 멀다
            out.append((titles[int(i)], score))
        return out

    def drop_vectors_if_changed(self, width: int) -> bool:
        """벡터 크기가 달라졌으면 통째로 버리고 다시 만들게 한다.

        모델을 바꾸면 차원이 달라진다(e5-small 384 → e5-base 768). 섞이면 곱셈이
        안 맞아 터지거나, 운 나쁘면 **말없이 엉뚱한 순위**가 나온다.
        """
        row = self.conn.execute(
            "SELECT length(vec) AS n, tvec IS NULL AS 제목없음 FROM vectors LIMIT 1").fetchone()
        # 제목 벡터가 없는 것은 옛 판이 만든 것이다. 크기가 같아도 다시 만든다 —
        # 안 그러면 새 판에서 그 항목만 조용히 검색에서 빠진다.
        if row is None or (row["n"] == width * 2 and not row["제목없음"]):
            return False
        self.conn.execute("DELETE FROM vectors")
        self.conn.execute("UPDATE notes SET vec_mtime = 0")
        self.conn.commit()
        self._vec_cache = None
        return True

    # 「비었다」를 셀 때 쓰는 글자들. **SQLite 의 `trim()` 은 공백만 떼고 줄바꿈은
    # 안 뗀다** — 앞머리 뒤에 빈 줄만 있는 항목이 「비지 않았다」로 세어졌다.
    BLANK = " " + chr(10) + chr(13) + chr(9)

    def blank_count(self) -> int:
        """본문이 빈 항목 수. 이런 항목은 일부러 벡터를 안 만든다."""
        return self.conn.execute(
            "SELECT count(*) FROM notes WHERE trim(body, ?) = ''", (self.BLANK,)).fetchone()[0]

    def _heal_vectors(self) -> None:
        """벡터가 빠진 항목을 **다시 만들 것으로 표시한다.**

        본문이 있는데 벡터가 없고 「아직 못 만든 것」에도 안 잡히면, 그 항목은 영영
        뜻 검색에서 빠진다 — 사람은 알 길이 없다. 실제로 그런 일이 났다(벡터 표에
        칸이 없던 판을 쓰는 동안 만들어진 항목들이 표시 없이 남았다).

        색인은 다시 만들 수 있는 것이라 표시만 되돌리면 뒤에서 알아서 채운다.
        """
        try:
            self.conn.execute(
                "UPDATE notes SET vec_mtime = 0 WHERE trim(body, ?) != '' "
                "AND path NOT IN (SELECT path FROM vectors)", (self.BLANK,))
            self.conn.commit()
        except sqlite3.OperationalError:
            pass          # 벡터 표가 아직 없다. 곧 만들어진다

    def _heal_search(self) -> None:
        """낱말 색인이 본체와 어긋나면 다시 채운다.

        `reindex`는 **바뀐 파일만** 다시 읽는다. 그래서 낱말 색인 표가 나중에 생기면
        (프로그램을 새 판으로 올렸을 때) 파일은 안 바뀌었으니 표가 영영 빈 채로 남고,
        검색이 조용히 옛 길로 떨어진다 — 실제로 109개 중 9개만 들어 있었다.

        파일을 다시 읽지 않는다. 본문은 이미 `notes`에 있다.
        """
        if not self.fts:
            return
        want = self.conn.execute("SELECT count(*) FROM notes").fetchone()[0]
        # **개수만 견주면 안 된다.** 같은 파일이 두 줄 들어가고 딴 파일 하나가 빠지면
        # 개수는 맞는데 속은 어긋난다 — 그러면 찾은 것에 **같은 항목이 두 번** 나오고
        # 여덟 자리 중 하나를 헛되이 쓴다(낯선 PC 에서 그렇게 걸렸다).
        # 서로 다른 파일이 몇 개인지까지 봐야 그 꼴이 잡힌다.
        have, apart = self.conn.execute(
            "SELECT count(*), count(DISTINCT path) FROM search").fetchone()
        if want == have == apart:
            return
        self.conn.execute("DELETE FROM search")
        self.conn.execute(
            "INSERT INTO search (rowid, path, title, body) "
            "SELECT rowid, path, title, body FROM notes")
        self.conn.commit()

    # --- 파일 -----------------------------------------------------------

    def path_of(self, title: str, created: str = "", kind: str = "") -> Path:
        """항목의 파일 자리.

        **이미 있으면 그 자리를 그대로 쓴다.** 사람이 옮겨 둔 폴더를 저장할 때마다
        되돌리면, 정리해 둔 것이 매번 흐트러진다.

        새로 만드는 것은 **층 아래 `연/월`** 폴더에 넣는다 — `raw/2026/09` 또는
        `wiki/2026/09`(오너 결정 2026-09-20 · 카파시 LLM Wiki 기준). 층은 `wiki.py` 가
        **갈래로** 정한다. 20년치를 한 폴더에 쌓으면 탐색기도 옵시디언도 버거워진다.
        """
        title = 제목맞춤(title)   # 맥(NFD)·못 쓰는 글자를 한 꼴로
        row = self.conn.execute(
            "SELECT path FROM notes WHERE title = ? ORDER BY mtime DESC LIMIT 1",
            (title,)).fetchone()
        if row and Path(row["path"]).exists():
            return Path(row["path"])
        stamp = (created or _now())[:7]              # YYYY-MM
        year, _, month = stamp.partition("-")
        if year.isdigit():
            # 층은 갈래가 정한다. 갈래를 모르면 `wiki/` 다 — **원본은 일부러 그렇게 적어야**
            # `raw/` 로 간다. 손 안 대는 자리에 실수로 들어가면 사람이 고치기 곤란하다.
            folder = self.root / wiki.자리(kind or "", f"{year}/{month}")
        else:
            folder = self.root
        folder.mkdir(parents=True, exist_ok=True)
        이름 = safe_title(title)
        자리 = folder / f"{이름}.md"
        # ★ **옛 판이 `-` 로 바꿔 저장한 파일**을 버리지 않는다. 그 파일은 이미 「질문- 답.md」로
        #   있고 색인 제목도 그렇다 — 새 규칙으로만 찾으면 **있는 글이 안 열린다.**
        #   ※ 여기 올 때 제목은 이미 전각으로 맞춰져 있다 — **되돌린 뒤에** 옛 규칙을 입혀야 한다.
        옛이름 = UNSAFE.sub("-", title.translate({ord(v): k for k, v in
                                                  ((chr(a), b) for a, b in _전각.items())})
                          ).strip().strip(".")[:80]
        if 옛이름 != 이름:
            옛줄 = self.conn.execute(
                "SELECT path FROM notes WHERE title = ? ORDER BY mtime DESC LIMIT 1",
                (옛이름,)).fetchone()
            if 옛줄 and Path(옛줄["path"]).exists():
                return Path(옛줄["path"])
        # ★★ **대소문자만 다른 제목이 서로를 조용히 덮었다.** 윈도우 파일 이름은
        #   대소문자를 안 가려서 `Alpha` 와 `alpha` 가 같은 파일이 된다 — 재 보니
        #   먼저 쓴 것이 사라졌다(둘 다 읽으면 나중 몸이 나왔다). 아무 말도 안 나온다.
        #   **이미 있는 파일의 제목이 나와 다르면** 지문 꼬리를 붙여 갈라 놓는다.
        #   ※ `자리.stem` 을 보면 안 된다 — 그건 **내가 적은 글자**지 파일의 진짜 이름이
        #     아니다. 폴더에서 대소문자를 무시하고 맞는 **실제 이름**을 찾아 견준다.
        #   ★★ **폴더를 늘 훑으면 안 된다.** 처음엔 새 글마다 `folder.glob("*.md")` 를 돌았는데,
        #     같은 연/월 폴더에 글이 쌓이자 **한 장 쓰는 데 17ms → 785ms**(2만 장 시험에서 45배)가
        #     됐다. 쓰기가 O(장수)가 된 것이다. 윈도우는 이름의 대소문자를 안 가리므로
        #     **`exists()` 가 먼저 True 를 준다** — 그때만 폴더를 훑어 진짜 이름을 본다.
        if not 자리.exists():
            return 자리
        있는것 = next((f for f in folder.glob("*.md")
                     if f.name.lower() == 자리.name.lower()), None)
        if 있는것 is not None and 있는것.name != 자리.name:
            자리 = folder / f"{이름}~{hashlib.sha256(title.encode()).hexdigest()[:6]}.md"
        return 자리

    def write(self, note: Note, at: str | Path = "") -> Path:
        """항목을 쓴다. **이미 있으면 신원(식별자·만든 날짜)을 물려받는다.**

        `at`을 주면 **그 파일**에 쓴다. 같은 제목이 두 폴더에 있을 때 제목으로 자리를
        다시 찾으면 2027년 것을 열어 놓고 2026년 파일에 저장하게 된다.

        AI가 같은 제목으로 다시 쓸 때마다 식별자와 만든 날짜가 새로 생기면, 20년 뒤에
        "이건 언제 처음 적은 거지"에 답할 수 없다.
        """
        try:
            old = self.read_at(at) if at else self.read(note.title)
        except Vanished:
            old = None
        except OSError as e:
            # 잠겨서 못 읽었다 — 신원(식별자·만든 날)도 지난 판도 못 챙기니 덮지 않는다(서버 507 · 화면 알림).
            raise WriteBlocked(str(at or note.title)) from e
        if old is not None:
            note.id = note.id or old.id
            note.created = note.created or old.created
        # 사람이 본문에 적은 `---` 블록을 진짜 앞머리로 올린다. 안 하면 두 겹이 된다.
        note.본문앞머리끌어올리기()
        note.id = note.id or f"{int(time.time() * 1000):x}"
        note.created = note.created or _now()
        path = Path(at) if at else self.path_of(note.title, note.created, note.kind)
        fresh = note.dumps()
        # 덮어쓰기 전에 지난 판을 남긴다. **내용이 같으면 안 남긴다** — 안 바뀐 저장이
        # 판만 늘리면 정작 되돌리고 싶은 지점이 밀려나 사라진다.
        if path.exists():
            try:
                was = read_text(path)
            except Vanished:
                was = fresh    # 사라졌으면 남길 지난 판도 없다
            except OSError as e:
                # ★★ **못 읽었다고 「없다」로 치면 안 된다.** 딴 프로그램이 잡고 있어 못 읽은 것인데
                #   예전엔 사라진 것과 같이 다뤄 **지난 판 없이 덮었다** — 사람이 옵시디언에서 고친 글이
                #   흔적 없이 사라지는 길이다. 멈추고 알린다(서버 507 · 화면 알림).
                raise WriteBlocked(str(path)) from e
            if was != fresh:
                # ★★ **밖에서 온 글은 5분 규칙에 안 걸리게 한다.**
                # 「치는 대로 저장」이라 판이 너무 늘지 않게 5분 안이면 지난 판을
                # 안 만드는데, 그 사이에 **사람이 옵시디언에서 고친 판**이 들어오면
                # 그것이 흔적 없이 사라진다. 되돌릴 수도, 사라진 줄 알 수도 없다.
                # 우리가 쓴 지문과 다르면 남의 손이 닿은 것이므로 **반드시 남긴다.**
                try:
                    self.keep_history(path, was, always=self._남의손인가(path, was))
                except WriteBlocked:
                    raise
                except OSError as e:
                    # 판을 못 남기면 덮지 않는다. 날것의 OSError 가 새면 서버가 507 대신 500 을 준다.
                    raise WriteBlocked(str(path)) from e
        _지문 = _해시(fresh)
        _atomic_write(path, fresh)
        self._index_file(path)
        # 우리가 쓴 글의 지문을 남긴다. 다음 덮어쓰기 때 이것과 견준다.
        self.conn.execute("UPDATE notes SET wrote = ? WHERE path = ?",
                          (_지문, str(path)))
        self.conn.commit()
        return path

    def _남의손인가(self, path: Path, 지금글: str) -> bool:
        """디스크에 있는 글이 **우리가 쓴 그 글이 아닌가.**

        ★ 「모르면 남긴다」 — 지문이 없으면 참으로 친다. 색인은 다시 만들 수 있는
        파생물이라 지문이 비어 있을 수 있는데, 그때 「우리가 쓴 것」으로 읽으면
        사람 손질이 조용히 사라진다. 잘못 남기면 이력이 한 판 느는 것뿐이다.
        """
        row = self.conn.execute("SELECT wrote FROM notes WHERE path = ?",
                                (str(path),)).fetchone()
        찍힌 = (row[0] if row else "") or ""
        return 찍힌 != _해시(지금글)

    def _글잠금(self, title: str) -> "_덧붙이기잠금":
        자리폴더 = (self.root.parent if str(self.index_path) == ":memory:"
                  else Path(str(self.index_path)).parent) / "vc-잠금"
        return _덧붙이기잠금(자리폴더, str(self.root) + "|" + 제목맞춤(title))

    def append(self, title: str, text: str, kind: str = "note", pinned: bool = False) -> Path:
        """있으면 뒤에 붙이고, 없으면 새로 만든다.

        AI가 관찰을 쌓는 기본 방식이다. 덮어쓰기를 기본으로 하면 어제 적은 것이
        오늘 적은 것에 조용히 지워진다 — 기억이 아니라 최신값 저장소가 된다.
        """
        with self._글잠금(title):
            old = self.read(title)
            if old is None:
                return self.write(Note(title=title, body=text, kind=kind, pinned=pinned))
            old.body = (old.body.rstrip() + chr(10) * 2 + text.strip()).strip()
            return self.write(old)

    def read_at(self, path: str | Path) -> Note | None:
        """**그 파일**을 읽는다. 제목이 겹칠 때 어느 쪽인지 우리가 고르지 않는다."""
        path = Path(path)
        if not path.exists():
            return None
        try:
            return Note.loads(path.stem, read_text(path))
        except Vanished:
            return None      # 읽는 사이 남이 지웠다

    def twins(self, title: str) -> list[Path]:
        """같은 제목을 가진 파일들. 하나뿐이면 빈 목록 — 굳이 알릴 것이 없다."""
        title = 제목맞춤(title)
        rows = self.conn.execute(
            "SELECT path FROM notes WHERE title = ? ORDER BY path", (title,)).fetchall()
        return [Path(r["path"]) for r in rows] if len(rows) > 1 else []

    def read(self, title: str) -> Note | None:
        title = 제목맞춤(title)   # 맥(NFD)·못 쓰는 글자를 한 꼴로
        path = self.path_of(title)
        if not path.exists():
            # ★★ **별칭으로도 열려야 한다.** 옵시디언은 `aliases` 로 글이 열리는데
            #   우리는 **링크만** 별칭으로 닿고(`neighbors` 는 됐다) 직접 열기는 404 였다.
            #   AI 꺼내기 2단이 바로 이 길을 쓰므로, 별칭이 적힌 글은 영영 못 펼쳤다.
            #   제목이 먼저고 그다음이 별칭이다 — 제목과 남의 별칭이 겹치면 제목이 이긴다.
            줄 = self.conn.execute(
                "SELECT title FROM aliases WHERE lower(alias) = lower(?)", (title,)).fetchone()
            if 줄 is None:
                return None
            path = self.path_of(줄["title"])
            if not path.exists():
                return None
        try:
            return Note.loads(path.stem, read_text(path))
        except Vanished:
            return None      # 읽는 사이 남이 지웠다

    def delete(self, title: str) -> bool:
        # 지난 판을 남기고 지우는 사이에 덧붙인 줄은 이력에도 없이 사라진다 — 한 잠금 안에서.
        with self._글잠금(title):
            return self._delete(title)

    def _delete(self, title: str) -> bool:
        path = self.path_of(title)
        if not path.exists():
            return False
        # ★★ **지우기 전에 한 판 남긴다.** 지난 판이 없는 글(한 번 쓰고 만 글)은
        #   지우면 **통째로 사라진다.** 5분 규칙도 건너뛴다 — 되돌릴 만한 지점이
        #   바로 이 자리다. 파일 한 장 값으로 실수를 되돌릴 수 있다.
        #   (`keep_history` 가 「확인창이 다시 돌아올 수 있다고 말해 놓고 못 돌아가면
        #    그건 거짓말이다」라고 적어 둔 그 뜻을 지우기에도 적용한다.)
        # ★★ **못 남기면 안 지운다.** 전엔 「못 남겨도 지우기는 되어야 한다」로 그냥 지워서, 이력 폴더가
        #   막힌 PC 에서는 **되돌릴 판 없이 글이 사라졌다** — 서버는 「되돌릴 수 있다」고 답하는데 거짓이 된다.
        #   지우기는 급한 일이 아니다. 멈추고 왜 못 했는지 알린다(서버 507 · 화면 알림).
        try:
            self.keep_history(path, read_text(path), always=True)
        except Vanished:
            return False        # 남기려는 사이 남이 지웠다 — 지울 것이 없다
        except OSError as e:
            # 글 이름·경로는 안 적는다 — 이 기록은 진단 묶음으로 밖에 나간다(「파일 이름은 안 담는다」).
            _알림(f"[지우기 멈춤] 지난 판을 못 남겨 안 지웠다 — {type(e).__name__}")
            raise WriteBlocked(str(path)) from e
        # 뒤에서 훑는 실이 방금 그 파일을 읽고 있을 수 있다. 윈도우는 **열려 있는
        # 파일을 못 지운다** — 잠깐 기다렸다 다시 하면 대개 통과한다. 검사에서 실제로
        # 났다(색인 중에 지우기).
        for wait in (0, 0.02, 0.05, 0.1, 0.2, 0.4):
            if wait:
                time.sleep(wait)
            try:
                path.unlink()
                break
            except PermissionError:
                continue
        else:
            return False
        # 색인 네 곳을 다 지운다. 하나라도 남기면 **없는 항목이 태그·별칭 검색에
        # 유령으로 계속 잡힌다** — 이름을 바꾼 뒤 옛 이름이 그렇게 남았다.
        with self.conn._잠금:              # 여러 줄이라 한 덩어리로(`_index_file` 과 같은 잠금)
            self._drop_search(str(path))
            self.conn.execute("DELETE FROM notes WHERE path = ?", (str(path),))
            for table, col in (("links", "src"), ("tags", "title"), ("aliases", "title")):
                self.conn.execute(f"DELETE FROM {table} WHERE {col} = ?", (path.stem,))
            self.conn.commit()
        return True

    # --- 인덱스 ---------------------------------------------------------

    def reindex(self) -> int:
        """바뀐 파일만 다시 읽는다. 사라진 파일은 인덱스에서 지운다.

        ponytail: 시작할 때 전체 디렉터리를 훑는다. 항목이 수천 개가 되어 시작이
        느려지면 그때 파일 감시로 바꾼다.
        """
        seen, changed = set(), 0
        # ★ 앞머리 표가 새로 생겨 비어 있으면 **이번 한 번은 전부** 다시 읽는다.
        #   파일이 안 바뀌었으니 평소 같으면 건너뛰는데, 그러면 `status:` 가 영영 0장이다.
        처음채우기 = getattr(self, "_앞머리채울까", False)
        known = {} if 처음채우기 else {
            r["path"]: r["mtime"]
            for r in self.conn.execute("SELECT path, mtime FROM notes")
        }
        todo = []
        for path in self.notes_files():
            # 목록을 만드는 사이에도 남이 지운다. **사라진 것은 없는 것으로 친다** —
            # `seen` 에 안 넣으므로 아래 정리 단계가 색인에서 알아서 뺀다.
            try:
                mtime = path.stat().st_mtime
            except OSError:
                continue
            key = str(path)
            seen.add(key)
            if known.get(key) != mtime:
                todo.append(path)
        # 파일 여는 값이 몸통이다 — 실제로 재보니 3000개 색인 16초 중 14.5초가
        # `open` 안에서 **기다리는** 시간이었다(윈도우 실시간 검사). 기다림은 실을
        # 나누면 겹쳐진다: 처음 읽기가 12.7초에서 4.1초로 줄었다. 색인 넣기는
        # 그대로 한 줄로 한다 — SQLite 연결은 하나뿐이다.
        texts: dict[Path, str] = {}
        if len(todo) > 200:
            with ThreadPoolExecutor(16) as pool:
                for path, text in zip(todo, pool.map(_read, todo)):
                    if text is not None:
                        texts[path] = text
        for path in todo:
            # 파일마다 커밋하면 커밋이 곧 값이다 — 2000개 첫 색인에 4.2초가 그렇게 갔다.
            # 묶어서 커밋한다. 중간에 죽어도 색인은 파일에서 다시 만들 수 있으니 안전하다.
            try:
                self._index_file(path, commit=False, text=texts.get(path))
            except (OSError, ValueError, UnicodeError):
                # **한 파일 때문에 나머지가 다 사라지면 안 된다.** 지우다 만 파일,
                # 잠긴 파일, 깨진 파일 하나가 20년 치를 통째로 안 보이게 만들었다.
                #
                # 파일 탓인 것만 넘긴다 — `Exception` 을 통째로 삼키면 우리 코드의
                # 버그까지 조용히 묻힌다.
                continue
            changed += 1
            if changed % 500 == 0:
                self.conn.commit()
        for gone in set(known) - seen:
            self.forget(gone, commit=False)
            changed += 1
        self.conn.commit()
        self._앞머리채울까 = False
        self._앞머리이름 = None
        return changed

    def forget(self, gone: str | Path, commit: bool = True) -> None:
        """색인에서만 지운다. 파일은 이미 없다(밖에서 지웠거나 옮겼다).

        **같은 제목이 아직 살아 있으면 딸린 것을 안 지운다.** 링크·태그·별칭은 경로가
        아니라 **제목**으로 묶여 있다. 그래서 파일을 다른 폴더로 옮기면, 새 자리에 방금
        넣은 링크를 옛 자리 정리가 지웠다 — 폴더 한 번 정리했을 뿐인데 링크가 통째로 사라진다.
        """
        gone = str(gone)
        stem = Path(gone).stem
        # ★ 「같은 제목이 남았나」 보고 딸린 것을 지우는 사이에 옮긴 글이 색인되면 **그 글의 링크를 지운다**
        #   — 위에서 막으려던 바로 그 사고다. 한 덩어리로 쥔다(`_index_file` 과 같은 잠금).
        with self.conn._잠금:
            self._drop_search(gone)
            self.conn.execute("DELETE FROM notes WHERE path = ?", (gone,))
            still = self.conn.execute(
                "SELECT 1 FROM notes WHERE title = ? LIMIT 1", (stem,)).fetchone()
            if still is None:
                self.conn.execute("DELETE FROM links WHERE src = ?", (stem,))
                self.conn.execute("DELETE FROM tags WHERE title = ?", (stem,))
                self.conn.execute("DELETE FROM aliases WHERE title = ?", (stem,))
            if commit:
                self.conn.commit()

    # --- 첨부 -----------------------------------------------------------

    def attach_root(self) -> Path:
        return self.root / ATTACH_DIR

    def save_attachment(self, data: bytes, suffix: str, stem: str = "") -> str:
        """첨부를 저장하고 **본문에 쓸 이름**을 돌려준다.

        연/월 폴더에 넣는다. 이름이 겹치면 뒤에 번호를 붙인다 — 덮어쓰면 다른 항목이
        가리키던 그림이 조용히 바뀐다.
        """
        stamp = _now()
        folder = self.attach_root() / stamp[:4] / stamp[5:7]
        folder.mkdir(parents=True, exist_ok=True)
        base = safe_title(stem or f"붙임 {stamp[:10]}")
        suffix = suffix if suffix.startswith(".") else "." + suffix
        name, n = f"{base}{suffix}", 2
        while (folder / name).exists():
            name, n = f"{base} {n}{suffix}", n + 1
        (folder / name).write_bytes(data)
        return name

    #: 목록 카드가 쓰는 작은 사진의 너비들. 아무 수나 받으면 폴더가 무한히 는다.
    THUMB_W = (320, 640)

    def thumbnail_path(self, name: str, w: int) -> Path | None:
        """작은 사진을 만들어 그 자리를 준다. 못 만들면 None(부르는 쪽이 원본을 준다).

        ★★ **왜 필요한가.** 폰 목록 카드가 사진마다 **원본을 통째로** 받아 갔다 —
        `cacheWidth` 는 그린 뒤에 줄일 뿐이라 받는 양은 그대로다(몇 MB씩). 목록만 훑어도
        데이터가 나가고, 앱을 껐다 켜면 또 받았다. 320px JPEG 면 보통 30~60KB 다.
        ※ 한 번 만들면 `_첨부/.썸네일/<너비>/` 에 남아 다음부터는 읽기만 한다.
        ※ HEIC 처럼 Pillow 가 못 읽는 꼴이면 None — 원본을 준다(폰이 그것을 캐시에 넣어
          **두 번은 안 받는다**). 폰에서 올린 사진은 올릴 때 이미 폰에 있으니 받지도 않는다.
        """
        if w not in self.THUMB_W:
            return None
        원본 = self.attachment_path(name)
        if 원본 is None or 원본.suffix.lower() not in IMAGE_EXT:
            return None
        자리 = self.attach_root() / ".썸네일" / str(w) / (원본.stem + ".jpg")
        try:
            if 자리.is_file() and 자리.stat().st_mtime >= 원본.stat().st_mtime:
                return 자리
            from PIL import Image

            자리.parent.mkdir(parents=True, exist_ok=True)
            with Image.open(원본) as 그림:
                그림 = 그림.convert("RGB")
                그림.thumbnail((w, w * 4))       # 세로로 긴 사진도 너비만 맞춘다
                그림.save(자리, "JPEG", quality=78, optimize=True)
            return 자리
        except Exception:
            # 못 만들어도 사진은 보여야 한다 — 원본으로 간다.
            return None

    def attachment_path(self, name: str) -> Path | None:
        """이름으로 첨부 파일을 찾는다. 없으면 None."""
        if not is_attachment(name):
            return None
        want = safe_title(name).lower()
        hit = next((p for p in 훑어내림(self.attach_root()) if p.name.lower() == want), None)
        if hit is None:                       # 사람이 다른 데 둔 경우까지 훑는다
            hit = next((p for p in 훑어내림(self.root)
                        if p.name.lower() == want and not self._is_history(p)), None)
        return hit

    def duplicates(self) -> list[tuple[str, int]]:
        """같은 이름이 여러 폴더에 있는 경우.

        이름이 곧 링크의 열쇠라 **저장소 전체에서 하나여야 한다.** 둘이면 `[[이름]]`이
        어디를 가리키는지 알 수 없다. 막지는 않고 드러낸다 — 사람이 옮기다 생긴 것을
        조용히 지우면 더 나쁘다.
        """
        rows = self.conn.execute(
            "SELECT title, count(*) AS n FROM notes GROUP BY title HAVING n > 1 "
            "ORDER BY n DESC, title")
        return [(r["title"], r["n"]) for r in rows]

    def _drop_search(self, path: str) -> None:
        """딸린 색인에서 뺀다. notes에서 지우기 **전에** 불러야 rowid를 알 수 있다."""
        self.conn.execute("DELETE FROM vectors WHERE path = ?", (path,))
        self._vec_cache = None
        if not self.fts:
            return
        row = self.conn.execute("SELECT rowid FROM notes WHERE path = ?", (path,)).fetchone()
        if row:
            self.conn.execute("DELETE FROM search WHERE rowid = ?", (row[0],))

    def _index_file(self, path: Path, commit: bool = True, text: str | None = None) -> None:
        # ★★ **한 글 색인은 여러 줄이다(notes 넣기 → 낱말 색인 지우고 넣기 → 링크·태그·별칭).**
        #   연결 잠금은 한 줄씩만 줄 세워서, 그 줄 사이에 딴 실의 다시 훑기가 같은 글을 넣으면
        #   `IntegrityError: constraint failed` 로 **덧붙이던 실이 죽었다**(부하 걸고 300 중 26 — 열린 문제 17).
        #   글 하나를 통째로 쥔다. RLock 이라 안의 execute 는 그대로 된다.
        with self.conn._잠금:
            return self._index_file_몸(path, commit, text)

    def _index_file_몸(self, path: Path, commit: bool = True, text: str | None = None) -> None:
        note = Note.loads(path.stem, read_text(path) if text is None else text)
        self.conn.execute(
            "INSERT INTO notes (path, id, title, kind, pinned, created, mtime, body) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(path) DO UPDATE SET "
            "id=excluded.id, title=excluded.title, kind=excluded.kind, "
            "pinned=excluded.pinned, created=excluded.created, mtime=excluded.mtime, "
            "body=excluded.body",
            (
                str(path),
                note.id,
                note.title,
                note.kind,
                int(note.pinned),
                note.created,
                path.stat().st_mtime,
                note.body,
            ),
        )
        if self.fts:
            # **rowid로 지운다.** `path`는 UNINDEXED라 그것으로 지우면 낱말 색인을
            # 통째로 훑는다 — 2만 건 첫 색인이 260초였다. notes의 rowid는 덮어써도
            # 그대로라 짝으로 쓸 수 있다.
            rid = self.conn.execute("SELECT rowid FROM notes WHERE path = ?",
                                    (str(path),)).fetchone()[0]
            self.conn.execute("DELETE FROM search WHERE rowid = ?", (rid,))
            self.conn.execute(
                "INSERT INTO search (rowid, path, title, body) VALUES (?, ?, ?, ?)",
                (rid, str(path), note.title, note.body))
        for table in ("links", "tags"):
            self.conn.execute(f"DELETE FROM {table} WHERE {'src' if table == 'links' else 'title'} = ?",
                              (note.title,))
        self.conn.execute("DELETE FROM aliases WHERE title = ?", (note.title,))
        self.conn.execute("DELETE FROM props WHERE title = ?", (note.title,))
        # ★ **AI 가 부어 넣은 글 안의 `[[ ]]` 는 「사람이 이은 것」이 아니다.**
        # 흡수한 글이 남의 항목 이름을 인용만 해도 굳은 선이 생겼다 — 상태줄의
        # 「적은 것」이 2에서 4로 늘었는데 사람은 아무것도 안 이었다.
        # 그러면 **「진한 선(사람이 말한 것)」과 「흐린 선(우리가 짐작한 것)」을
        # 갈라 놓은 뜻이 흐려진다.** 위키 문법을 쓰는 자리를 흡수하면 이 수가
        # 사람이 실제로 이은 것보다 훨씬 커진다.
        흐림 = 1 if str((note.extra or {}).get("지은이", "")) == "문지기" else 0
        if True:
            self.conn.executemany(
                "INSERT OR IGNORE INTO links (src, dst, heading, 흐림) "
                "VALUES (?, ?, ?, ?)",
                [(note.title, dst, head, 흐림) for dst, head in note.links()],
            )
        self.conn.executemany(
            "INSERT OR IGNORE INTO tags (title, tag) VALUES (?, ?)",
            [(note.title, t) for t in note.tags()],
        )
        # 이미 남이 쓰는 별칭은 무시한다 — 한 이름이 두 곳을 가리키면 링크가 어디로
        # 갈지 알 수 없다. 먼저 쓴 쪽이 이긴다.
        self.conn.executemany(
            "INSERT OR IGNORE INTO aliases (alias, title) VALUES (?, ?)",
            [(a, note.title) for a in note.aliases if a != note.title],
        )
        # 앞머리 값. 목록·사전은 글로 펴서 담는다 — 찾을 때는 「그 말이 들었나」면 된다.
        self.conn.executemany(
            "INSERT OR IGNORE INTO props (title, key, value) VALUES (?, ?, ?)",
            [(note.title, str(k), 앞머리값(v)) for k, v in (note.extra or {}).items()
             if str(k).strip() and v not in (None, "")],
        )
        self._앞머리이름 = None      # 새 이름이 생겼을 수 있다
        if commit:
            self.conn.commit()

    # --- 조회 -----------------------------------------------------------

    #  좁히는 말이 걸리는 곳. 값 하나를 물음표로 받는다.
    _NARROW_SQL = {
        "태그": ("EXISTS (SELECT 1 FROM tags g WHERE g.title = n.title "
               "AND g.tag LIKE ? ESCAPE '\\')"),
        "경로": "n.path LIKE ? ESCAPE '\\'",
        "종류": "n.kind = ?",
        "해": "substr(n.created, 1, 4) = ?",
        "제목": "n.title LIKE ? ESCAPE '\\'",
    }
    _NARROW_ARG = {
        "태그": lambda v: 라이크(v.lstrip("#")) + "%",
        # ★★ **윈도우 경로는 `\` 인데 사람은 `/` 로 적는다.** `path:2026/09` 가 영영
        #   안 걸렸다 — 0장이 나오는데 왜인지도 안 보였다. 적는 대로 걸리게 바꿔 준다.
        #   ※ 전에는 `chr(92)` 로 **늘** 바꿔서, 「맥·리눅스에서는 아무 일도 안 일어난다」는
        #     주석과 달리 맥에서는 `2026/09` 가 `2026\09` 가 되어 되레 0장이 됐다.
        #     `os.sep` 를 쓰면 윈도우에서만 바뀌고 맥은 적은 그대로 간다.
        "경로": lambda v: "%" + 라이크(v.replace("/", os.sep)) + "%",
        "종류": lambda v: v,
        "해": lambda v: v,
        "제목": lambda v: "%" + 라이크(제목맞춤(v)) + "%",
    }

    #  앞머리로 좁히기. 이름과 값 **둘**을 받으므로 물음표가 두 개다.
    _앞머리SQL = ("EXISTS (SELECT 1 FROM props p WHERE p.title = n.title "
               "AND p.key = ? AND p.value LIKE ? ESCAPE '\\')")

    def _narrow_sql(self, narrow: list[tuple[str, str]]) -> tuple[list[str], list[str]]:
        """좁히는 말을 SQL 조건으로. 모르는 이름은 조용히 버린다."""
        where, args = [], []
        for kind, value in narrow:
            drop = kind.startswith("빼기:")
            base = kind[3:] if drop else kind
            if base.startswith("앞머리:"):
                # 값은 **앞자리 일치**로 본다(태그와 같은 규칙) — `status:resolved` 가
                # 「resolved  # 원인 확정…」처럼 뒤에 말이 붙은 값도 잡는다.
                where.append(f"NOT ({self._앞머리SQL})" if drop else self._앞머리SQL)
                args.extend([base[4:], 라이크(value) + "%"])
                continue
            sql = self._NARROW_SQL.get(base)
            if sql is None:
                continue
            where.append(f"NOT ({sql})" if drop else sql)
            args.append(self._NARROW_ARG[base](value))
        return where, args

    def 앞머리모음(self, titles) -> dict:
        """그 글들의 앞머리를 `{제목: {이름: 값}}` 으로. 좁히기 제안이 이것을 센다."""
        titles = [t for t in titles if t]
        if not titles:
            return {}
        낸다: dict = {}
        칸 = ",".join("?" * len(titles))
        for t, k, v in self.conn.execute(
                f"SELECT title, key, value FROM props WHERE title IN ({칸})", titles):
            낸다.setdefault(t, {})[k] = v
        return 낸다

    def 폴더나무(self) -> list[tuple[str, int, int]]:
        """창고의 폴더를 `(보일 이름, 깊이, 글 수)` 로. **빈 폴더는 안 낸다.**

        옵시디언의 「파일 탐색기」가 하는 일이다. VC 는 새 글을 연/월에 두지만
        **사람이 옮겨 둔 자리는 지키므로**, 창고에는 제 나름의 폴더가 생긴다.
        """
        셈: dict[str, int] = {}
        for (자리,) in self.conn.execute("SELECT path FROM notes"):
            try:
                안 = Path(자리).parent.relative_to(self.root).as_posix()
            except ValueError:
                continue
            if 안 == "." or any(조각.startswith(".") for 조각 in Path(안).parts):
                안 = "" if 안 == "." else 안
                if 안 == "" :
                    셈[""] = 셈.get("", 0) + 1
                continue
            셈[안] = 셈.get(안, 0) + 1
        # 위 폴더도 세어 둔다 — 「2026」 을 눌러 그 해 전부를 볼 수 있어야 한다
        모두: dict[str, int] = {}
        for 안, 수 in 셈.items():
            모두[안] = 모두.get(안, 0) + 수
            조각 = Path(안).parts if 안 else ()
            for i in range(1, len(조각)):
                위 = "/".join(조각[:i])
                모두[위] = 모두.get(위, 0) + 수
        낸다 = []
        for 안 in sorted(x for x in 모두 if x):
            조각 = Path(안).parts
            낸다.append((조각[-1], len(조각) - 1, 모두[안]))
        if 셈.get(""):
            낸다.insert(0, ("(맨 위)", 0, 셈[""]))
        return 낸다

    def 앞머리세기(self, 최대: int = 20) -> list[tuple[str, int]]:
        """어떤 앞머리가 몇 장에 붙어 있나. **많은 것부터.**

        옵시디언의 「속성」 칸이 하는 일이다 — 볼트가 무엇을 적어 왔는지 한눈에 본다.
        글마다 다른 것(`들인곳`·`id`)은 세어 봐야 고르는 데 안 쓰이므로 뺀다.
        """
        안셈 = ("들인곳", "id", "created", "지은이")
        빈칸 = ",".join("?" * len(안셈))
        return [(r[0], r[1]) for r in self.conn.execute(
            f"SELECT key, count(*) c FROM props WHERE key NOT IN ({빈칸}) "
            "GROUP BY key ORDER BY c DESC, key LIMIT ?", (*안셈, 최대))]

    def 앞머리값들(self, 이름: str, 최대: int = 20) -> list[tuple[str, int]]:
        """그 앞머리에 어떤 값이 몇 장인지. **많은 것부터.**"""
        낸다: dict[str, int] = {}
        for (값,) in self.conn.execute("SELECT value FROM props WHERE key = ?", (이름,)):
            깔끔 = str(값).split("#")[0].strip()
            if not 깔끔:
                continue
            if len(깔끔) > 40:          # 긴 글귀는 고르는 말이 못 된다
                깔끔 = 깔끔[:39] + "…"
            낸다[깔끔] = 낸다.get(깔끔, 0) + 1
        return sorted(낸다.items(), key=lambda kv: (-kv[1], kv[0]))[:최대]

    def 앞머리이름들(self) -> frozenset:
        """창고가 실제로 지닌 앞머리 이름들. 검색이 이것으로 `이름:값` 을 가른다."""
        있는것 = getattr(self, "_앞머리이름", None)
        if 있는것 is None:
            있는것 = frozenset(r[0] for r in self.conn.execute("SELECT DISTINCT key FROM props"))
            self._앞머리이름 = 있는것
        return 있는것

    _정규식꼴 = re.compile(r"(?:(?<=\s)|^)/((?:\\/|[^/\s]|(?<=\\)\s)(?:\\/|[^/])*)/(?=\s|$)")

    def search(self, q: str, k: int = 8, 세기: bool = True) -> list[sqlite3.Row]:
        """`/정규식/` 을 먼저 뽑아 거르고, 나머지는 `_search` 로 찾는다.

        ★ 옵시디언의 `/정규식/` 검색. 낱말 색인은 `ERR-1234` 같은 **꼴**을 못 찾는다(기호에서 끊긴다).
        제목·본문에 그 꼴이 든 것만 남긴다. 다른 말이 같이 오면 그 말로 넉넉히 찾은 뒤 거른다.
        틀린 정규식이면 0장 — 짐작해서 넓히지 않는다.
        """
        정규식들: list[str] = []
        q = self._정규식꼴.sub(lambda m: (정규식들.append(m.group(1)), " ")[1], q)
        if not 정규식들:
            return self._search(q, k, 세기)
        try:
            # ponytail: 파이썬 re 는 시간 한도가 없다 — 길이만 막는다. 되돌이 폭주가 보이면 regex 모듈의 timeout 으로
            거를 = [re.compile(p, re.IGNORECASE) for p in 정규식들 if len(p) <= 200]
        except re.error:
            return []
        if len(거를) != len(정규식들):
            return []
        if q.strip():
            후보 = self._search(q, max(k * 20, 200), 세기=False)
        else:
            후보 = self.conn.execute("SELECT * FROM notes ORDER BY pinned DESC, created DESC").fetchall()
        나온 = [r for r in 후보
               if all(g.search(r["title"] + chr(10) + (r["body"] or "")) for g in 거를)
               and Path(r["path"]).exists()][:k]
        if 나온 and 세기:
            self.conn.executemany(
                "UPDATE notes SET used_at = ?, use_count = use_count + 1 WHERE path = ?",
                [(time.time(), r["path"]) for r in 나온])
            self.conn.commit()
        return 나온

    def _search(self, q: str, k: int = 8, 세기: bool = True) -> list[sqlite3.Row]:
        """낱말 색인으로 찾는다. 좁히는 말도 받는다.

        - `모델 선택` — 낱말은 **모두** 들어 있어야 한다. 뒤에 조사가 붙어도 걸리도록
          앞자리만 맞춘다(`저장*`이 `저장을`·`저장한다`를 잡는다).
        - `"정확한 구절"` — 그 순서 그대로.
        - `-실패` — 그것이 든 것은 뺀다.
        - `tag:할일` `path:prompts` `kind:skill` `year:2026` — 범위를 좁힌다.
          한글로도 받는다(`태그:` `경로:` `종류:` `해:`).

        차례는 bm25가 매기되 제목에 든 것을 12배로 친다. 고정된 항목은 늘 먼저다
        — 사용자가 직접 말한 것은 관찰에 밀리지 않는다(결정 22).
        """
        q = unicodedata.normalize("NFC", q)           # 맥(NFD)에서 친 물음도 같게
        ask = Ask(q, self.앞머리이름들())
        rows: list[sqlite3.Row] = []
        where, args = self._narrow_sql(ask.narrow)
        match = ask.match() if self.fts else ""

        if match or where:
            if match:
                sql = ("SELECT n.* FROM search s JOIN notes n ON n.path = s.path "
                       "WHERE s.search MATCH ?")
                head: list[str] = [match]
                order = "n.pinned DESC, bm25(s.search, 12.0, 1.0)"
            else:
                # 좁히는 말만 왔다(`tag:할일`). 낱말 색인을 거칠 이유가 없다.
                sql, head = "SELECT n.* FROM notes n WHERE 1=1", []
                order = "n.pinned DESC, n.created DESC"
            if where:
                sql += " AND " + " AND ".join(where)
            try:
                rows = self.conn.execute(f"{sql} ORDER BY {order} LIMIT ?",
                                         (*head, *args, k)).fetchall()
            except sqlite3.OperationalError:
                rows = []   # 색인이 아직 안 찼거나 문법에 안 맞는 물음

        if not rows and not ask.narrow:
            # 낱말로 안 끊기는 물음(기호만, 부분 글자)은 옛 길로 훑는다. 느리지만
            # **아무것도 못 찾는 것보다는 낫다.** 좁히는 말이 있었다면 안 한다 —
            # `tag:없는것`이 0건인 것은 옳은 답이지 실패가 아니다.
            rows = self.conn.execute(
                "SELECT * FROM notes WHERE title LIKE ? ESCAPE '\\' "
                "   OR body LIKE ? ESCAPE '\\' "
                "ORDER BY pinned DESC, created DESC LIMIT ?",
                (f"%{라이크(q)}%", f"%{라이크(q)}%", k),
            ).fetchall()
        # ★ 뜻으로 채우기 **전에** 낱말로 몇 개 걸렸는지 남긴다. 화면이 이것 없이
        #   「관련 N개야」라고 해서, 어느 글에도 없는 말에도 관련이 있다고 말했다(시험 쪽 9).
        self.낱말로찾은수 = len(rows)
        rows = self._blend_meaning(ask, rows, k)
        # **같은 것을 두 번 내보내지 않는다.** 낱말 색인이 어긋나면 조인이 같은 파일을
        # 두 줄로 돌려준다. 위에서 고치기는 하지만, 찾는 길에도 그물을 둔다 —
        # 여덟 자리는 좁고, 한 줄을 헛되이 쓰면 진짜 답이 밖으로 밀린다.
        본 = set()
        rows = [r for r in rows if not (r["path"] in 본 or 본.add(r["path"]))]
        # ★ **제목이 물음과 똑같으면 그것부터 내놓는다.**
        # bm25 가 제목을 12배로 쳐도 **거의 같은 형제 제목**한테 진다 —
        # 「아, 그렇군요」를 물으면 「아, 그렇군요!」가 1등이고, 「안 먹는 말투」를
        # 물으면 그 낱말이 본문에 여러 번 나오는 보고서가 1등이었다(시험 쪽 새-①).
        # 사람이 제목을 그대로 치는 것은 **그 글을 달라는 말**이고, AI 가 회상할 때도
        # 제목으로 부른다 — 이 창고는 AI 의 바깥 기억이라 여기가 곧 성능이다.
        #
        # 가중치를 올리는 쪽은 안 골랐다. 문턱·배수를 흔들면 **딴 것이 조용히 밀린다**
        # (이 프로젝트에서 여러 번 겪었다). 똑같을 때만 앞으로 당기면 **그 물음
        # 하나만** 달라지고 나머지 차례는 그대로다.
        # ★ **따옴표를 친 물음도 여기 걸려야 한다.** 처음엔 물음 글자를 그대로 견줬는데
        # `"안 먹는 말투"` 는 따옴표째라 제목과 영영 안 맞아, **따옴표를 붙이면 제목
        # 우선이 조용히 꺼졌다**(시험 쪽 라 — 그 제목 글이 3등으로 되돌아갔다).
        # 사람은 「정확히 이거」를 바랄수록 따옴표를 치는데 하필 그때 꺼진 것이다.
        # 구절도 후보에 넣는다.
        후보 = {q.strip()} | {p.strip() for p in ask.phrases}
        후보.discard("")
        if 후보:
            rows.sort(key=lambda r: (r["title"].strip() not in 후보, ))
        # ★★ **없어진 파일이 계속 걸렸다.** 밖에서(옵시디언·탐색기) 글을 지우면 색인은
        #   다음 훑기 전까지 그대로라, 검색은 그 글을 주는데 펼치면 404 다 — AI 는
        #   찾은 줄 알고 2단을 부르고 800자를 버린다. 사람 화면에서는 빈 글이 열린다.
        #   내놓기 직전에 **몇 장만** 확인한다(다섯 장이면 stat 다섯 번, 0.1ms 수준).
        #   없으면 색인에서도 지운다 — 그냥 빼기만 하면 다음 물음에서 또 걸린다.
        살아있는 = []
        for r in rows:
            if Path(r["path"]).exists():
                살아있는.append(r)
            else:
                self.forget(r["path"])
        rows = 살아있는
        if rows and 세기:
            self.conn.executemany(
                "UPDATE notes SET used_at = ?, use_count = use_count + 1 WHERE path = ?",
                [(time.time(), r["path"]) for r in rows],
            )
            self.conn.commit()
        return rows

    def _blend_meaning(self, ask: "Ask", rows: list, k: int) -> list:
        """낱말로 찾은 것 **뒤에** 뜻으로 더 찾은 것을 붙인다.

        차례를 섞지 않는다. 점수를 합쳐 섞어 봤더니 `LogMapping`을 찾았을 때
        정작 `logmapping` 문서가 3등으로 밀렸다 — **낱말이 딱 맞은 것이 뜻만
        비슷한 것에 밀리면** 검색을 못 믿게 된다.

        낱말이 하나도 안 맞을 때가 뜻 검색이 빛나는 자리다. 실제로 재보니
        "작년에 배포 엎었던 거"·"옵시디언에 어떻게 저장하지"는 낱말로는 **0건**이고
        뜻으로는 정확히 맞힌다.

        뜻 검색이 꺼져 있으면(모델 없음) 아무 일도 안 일어난다.
        """
        if len(rows) >= k or (not ask.terms and not ask.phrases):
            return rows            # 이미 찼거나, 좁히기만 한 물음이다
        # ★ **따옴표를 쳤으면 뜻으로 채우지 않는다.** 구절은 「정확히 이것」이라는
        # 말인데, 낱말로 좁힌 자리를 뜻 검색이 도로 채우면 **따옴표가 아무 일도 안 한
        # 것처럼 보인다** — 실사용에서 `"소리 내어 읽으면"` 과 따옴표 없는 물음의
        # 결과가 목록도 순서도 똑같이 나왔다(시험 쪽 ⑥). 그 구절이 안 보이는 글이
        # 2등에 남아 있는데 따옴표를 붙여도 안 빠졌다. 좁히라고 친 것을 넓히면 안 된다.
        if ask.phrases:
            return rows
        where, args = self._narrow_sql(ask.narrow)
        # ★★ **좁힌 뒤에 세야 한다. 세고 나서 좁히면 전멸한다.**
        #   `kind:결정` 처럼 좁혀 물으면 뜻으로 뽑은 k 개를 그 조건으로 걸러 내는데,
        #   그 k 개 안에 그 갈래가 하나도 없으면 **0장**이 된다. 실제로 그랬다 —
        #   오너 창고(2794장, 결정은 120장)에서 「kind:결정 …」 이 한 장도 안 나왔다.
        #   `--찾기점수` 의 `--빼고` 가 **이미 같은 교훈을 적어 뒀는데**(넉넉히 뽑아 놓고
        #   빼고 나서 위에서 여덟을 센다) 여기서 되풀이됐다.
        #   좁힘이 있으면 넉넉히 뽑는다. 좁힘이 없으면 예전 그대로 — 값을 더 안 쓴다.
        #   ★ 좁힘이 없어도 넉넉히 뽑는다 — **갈래를 골고루 섞으려면 섞을 것이 있어야 한다.**
        #     `semantic` 은 행렬곱 한 번이라 k 를 늘려도 드는 값이 거의 같다(정렬만 는다).
        hits = self.semantic(ask.plain(), k=k * 40)
        if not hits:
            return rows
        seen = {r["title"] for r in rows}
        out = list(rows)
        # ★★ **한 갈래가 목록을 다 차지하면 다른 갈래의 답이 영영 안 보인다.**
        #   오너 창고(2794장)는 대화 로그 조각(`kind: 일`)이 2373장이라, 뜻으로 뽑은
        #   다섯 장이 전부 그 조각으로 채워졌다. 정답은 대부분 결정·규칙·일정 쪽인데도.
        #   [잰 것] 갈래당 상한을 두니 찾은 물음이 **6/20 → 9~10/20** 으로 늘었다
        #   (같은 다섯 장·같은 글자 수인데). 문턱이 아니라 **k 와의 관계**로 정한다.
        #   ※ **뜻으로 채우는 자리에만** 건다. 낱말로 딱 맞은 것은 안 건드린다 —
        #     그것이 뜻만 비슷한 것에 밀리면 검색을 못 믿게 된다(앞서 겪은 자리다).
        # **갈래를 돌아가며 한 장씩 뽑는다**(라운드로빈). 갈래가 하나뿐인 창고에서는
        # 그냥 차례대로 뽑는 것과 같아 손해가 없고, 여러 갈래면 골고루 섞인다.
        묶음: dict[str, list] = {}
        차례: list[str] = []
        for title, _ in hits:
            if title in seen:
                continue
            sql = "SELECT * FROM notes n WHERE n.title = ?"
            if where:
                sql += " AND " + " AND ".join(where)   # 좁힌 조건은 뜻에도 그대로
            got = self.conn.execute(sql, (title, *args)).fetchone()
            if got is None:
                continue
            갈 = got["kind"] or "note"
            if 갈 not in 묶음:
                묶음[갈], _ = [], 차례.append(갈)
            묶음[갈].append(got)
        # 낱말로 이미 든 갈래는 **한 바퀴 뒤로 민다** — 그쪽은 이미 자리를 얻었다.
        먼저든갈래 = {r["kind"] or "note" for r in rows}
        차례.sort(key=lambda 갈: 갈 in 먼저든갈래)
        층 = 0
        while len(out) < k:
            더넣었나 = False
            for 갈 in 차례:
                if len(out) >= k:
                    break
                if 층 < len(묶음[갈]):
                    골라 = 묶음[갈][층]
                    out.append(골라)
                    seen.add(골라["title"])
                    더넣었나 = True
            if not 더넣었나:
                break
            층 += 1
        return out

    def titles_like(self, part: str, k: int = 12) -> list[str]:
        """`[[`를 칠 때 띄울 제목들. 별칭도 같이 준다.

        목록을 미리 들고 있지 않는다 — 2만 개를 화면 고칠 때마다 끌어오면 그것만으로
        느려진다. 치는 순간에만 묻고 **k개까지만** 받는다.

        딱 맞는 것이 맨 위, 다음이 앞자리가 맞는 것, 그 다음이 자주 연 것이다.
        `eb`를 다 쳤는데 `eb-stage0-decisions`가 먼저 뜨면 한 번 더 손이 간다.
        """
        part = 제목맞춤(part)   # 「질문?」 으로 쳐도 「질문？ 답」 이 걸리게
        like = f"%{라이크(part)}%"
        head = f"{라이크(part)}%"
        rows = self.conn.execute(
            "SELECT title AS name, (title = ?) AS same, "
            "       (title LIKE ? ESCAPE '\\') AS head, use_count "
            "  FROM notes WHERE title LIKE ? ESCAPE '\\' "
            "UNION ALL "
            "SELECT alias AS name, (alias = ?) AS same, "
            "       (alias LIKE ? ESCAPE '\\') AS head, 0 "
            "  FROM aliases WHERE alias LIKE ? ESCAPE '\\' "
            "ORDER BY same DESC, head DESC, use_count DESC, name LIMIT ?",
            (part, head, like, part, head, like, k),
        ).fetchall()
        return list(dict.fromkeys(r["name"] for r in rows))

    def rename(self, old: str, new: str) -> bool:
        # ★★ 「새 이름이 없나」 보고 쓰는 사이에 남이 그 이름을 만들면(두 이름 바꾸기가 같은 새 이름으로,
        #   AI 가 그 제목으로 새 글을) 한쪽 글이 덮여 사라진다. 이름 바꾸기끼리 줄 세우고 새 이름을 잠근다.
        #   순서는 늘 「이름 바꾸기 → 새 이름 → 링크 고칠 글」이라 서로 물고 멈추지 않는다.
        with _이름바꾸기잠금, self._글잠금(new):
            return self._rename(old, new)

    def _rename(self, old: str, new: str) -> bool:
        """항목 이름을 바꾸고 **그것을 가리키던 링크도 같이 고친다.**

        파일만 바꾸면 다른 노트의 `[[옛이름]]`이 허공을 가리켜 그래프에서 연결이
        통째로 끊긴다. 이름은 곧 열쇠라, 옮길 때는 가리키는 쪽도 같이 옮겨야 한다.

        새 이름이 이미 있으면 안 바꾼다 — 덮어쓰면 기록이 사라진다.
        """
        old, new = 제목맞춤(old), 제목맞춤(new)
        note = self.read(old)
        if note is None or self.read(new) is not None:
            return False
        # ★★ **하려는 일을 먼저 적는다.** 이름 바꾸기는 **여러 파일**을 건드린다 —
        # 항목을 옮기고, 이력 폴더를 옮기고, 가리키던 `[[옛이름]]` 을 전부 고친다.
        # `os.replace` 의 원자성은 **한 파일까지만** 덮어 준다. 중간에 죽으면
        # 그래프가 반쯤 끊긴 채로 남고 **끊긴 줄조차 모른다.**
        #
        # 이건 **진실을 옮기는 저널이 아니다** — 파일은 계속 진실이다. 끝나면 지우는
        # **재개용 쪽지**라, 이게 남아 있으면 「하다 말았다」는 뜻이다.
        쪽지 = self.root.parent / "vc-이름바꾸다만것.txt"
        try:
            쪽지.write_text(old + chr(9) + new + chr(10), encoding="utf-8")
        except OSError:
            pass          # 못 적어도 이름 바꾸기 자체는 한다
        # **지난 판도 같이 옮긴다.** 이력 폴더는 이름으로 잡히므로, 안 옮기면
        # 옛 이름 폴더에 남아 새 이름으로는 못 찾는다 — 이름을 바꾼 항목은
        # 되돌릴 수 없게 된다. 낯선 PC 실사용에서 「화면은 지난 판이 있다 하고
        # 지시는 없다 한다」로 드러났다.
        was = self.history_dir(self.path_of(old))
        self.delete(old)
        # ★★ **이름만 바꾸는 것이지 딴 것을 버리는 게 아니다.**
        # 예전에는 제목·본문·갈래·고정·만든날만 옮기고 **`extra` 를 통째로 버렸다** —
        # `출처`·`지은이`·`들인이유` 와 사람이 적은 `type`·`status` 가 다 사라졌다.
        # 그 값들은 **원본 사실이라 나중에 되살릴 수가 없다**(어디서 온 글인지는
        # 그때만 안다). 실제로 이름 바꾼 35개가 **흡수분인데 사람이 만든 글로**
        # 보이게 됐다 — 다시 붓기 막이가 그걸 보고 막아선다.
        # 별칭도 같이 옮긴다. 안 옮기면 옛 별칭으로 부르던 링크가 끊긴다.
        note.title = new
        self.write(note)
        now = self.history_dir(self.path_of(new))
        if was.is_dir() and was != now:
            try:
                now.parent.mkdir(parents=True, exist_ok=True)
                if now.is_dir():
                    for past in was.glob("*.md"):
                        past.replace(now / past.name)   # 이미 있으면 합친다
                    was.rmdir()
                else:
                    was.replace(now)
            except OSError as e:
                # 못 옮겨도 이름 바꾸기 자체는 살린다. 지난 판은 옛 이름 폴더에 그대로 있다 — 어디 있는지 남긴다.
                _알림(f"[이름 바꾸기] 지난 판을 못 옮겼다(옛 이름 폴더에 남음) — {type(e).__name__}")   # 경로에 글 이름이 든다
        # ★★ **`[[옛것]]` 만 고치면 반만 고치는 것이다.** 링크에는 네 꼴이 있다:
        #   `[[옛것]]` · `[[옛것#소제목]]` · `[[옛것|보일 글]]` · `![[옛것]]`(끼워넣기).
        #   글자로만 바꿀 때는 첫 꼴만 걸려 **나머지가 허공을 가리켰다**(재 보고 찾았다).
        #   같은 정규식(`LINK_RE`)으로 바꾼다 — 찾는 쪽과 고치는 쪽이 갈리면 또 새 나간다.
        def 바꿔(m: "re.Match") -> str:
            이름, 소제목, 보일 = m.group(1), m.group(2), m.group(3)
            if 제목맞춤(이름.strip()) != 제목맞춤(old):
                return m.group(0)
            끼움 = "!" if m.group(0).startswith("!") else ""
            안 = new + (f"#{소제목}" if 소제목 else "") + (f"|{보일}" if 보일 else "")
            return f"{끼움}[[{안}]]"

        고치개 = re.compile(r"!?" + LINK_RE.pattern)
        for path in self.notes_files():   # 하위 폴더까지
            # 훑는 동안 남이 지울 수 있다. 한 파일 때문에 **나머지 링크가 안 고쳐지면**
            # 그래프가 반쯤 끊긴 채로 남는다 — 그게 더 나쁘다.
            try:
                if f"[[{old}" not in read_text(path):
                    continue
            except (Vanished, OSError):
                continue
            # ★ 링크 고치기도 읽고-바꾸고-쓰기다 — 그 사이 덧붙인 줄이 사라지지 않게 같은 잠금 안에서 다시 읽는다.
            with self._글잠금(path.stem):
                try:
                    text = read_text(path)
                except (Vanished, OSError):
                    continue
                새글 = 고치개.sub(바꿔, text)
                if 새글 != text:
                    try:
                        _atomic_write(path, 새글)
                    except (Vanished, OSError, WriteBlocked):
                        continue
        self.reindex()
        쪽지.unlink(missing_ok=True)      # 끝났으니 쪽지를 지운다
        return True

    def 이름바꾸다만것(self) -> tuple[str, str] | None:
        """하다 만 이름 바꾸기가 있으면 (옛이름, 새이름). 없으면 `None`.

        켤 때 한 번 본다. 남아 있으면 **여러 파일 중 일부만 고쳐진 상태**라
        그래프가 반쯤 끊겨 있다 — 사람에게 알려 다시 하게 한다.
        """
        쪽지 = self.root.parent / "vc-이름바꾸다만것.txt"
        try:
            글 = 쪽지.read_text(encoding="utf-8").strip()
        except OSError:
            return None
        옛, 탭, 새 = 글.partition(chr(9))
        return (옛, 새) if 탭 and 옛 and 새 else None

    def resolve(self, name: str) -> str | None:
        """[[이름]]이 실제로 가리키는 항목. 없으면 None(= 미해결 링크).

        제목이 먼저고 그다음이 별칭이다. 제목과 남의 별칭이 겹치면 제목이 이긴다 —
        자기 이름으로 불렸는데 딴 데로 가면 안 된다.
        """
        if self.conn.execute("SELECT 1 FROM notes WHERE title = ?", (name,)).fetchone():
            return name
        맞춘 = 제목맞춤(name)
        if 맞춘 != name and self.conn.execute(
                "SELECT 1 FROM notes WHERE title = ?", (맞춘,)).fetchone():
            return 맞춘
        row = self.conn.execute("SELECT title FROM aliases WHERE alias = ?", (name,)).fetchone()
        if row:
            return row["title"]
        # 경로로 건 링크 — 옵시디언은 `[[폴더/노트]]`를 받는다. 실제 기록에 그렇게 적힌
        # 링크가 있어서, 마지막 조각으로 한 번 더 찾는다.
        if "/" in name or "\\" in name:
            tail = name.replace("\\", "/").rsplit("/", 1)[-1].strip()
            if tail and tail != name:
                return self.resolve(tail)
        return None

    def _names(self, title: str) -> list[str]:
        """이 항목을 가리킬 수 있는 모든 이름 — 제목과 별칭들."""
        title = 제목맞춤(title)
        alias = [r["alias"] for r in self.conn.execute(
            "SELECT alias FROM aliases WHERE title = ?", (title,))]
        return [title, *alias]

    def neighbors(self, title: str) -> list[str]:
        """그래프 화면이 쓸 연결. 나가는 링크와 들어오는 링크를 함께 준다.

        나가는 링크는 **가리키는 실제 항목으로 바꿔서** 준다. 별칭으로 걸린 링크가
        따로 떨어진 점으로 보이면 그래프가 두 배로 부푼다. 아직 없는 항목을 가리키는
        링크(미해결)는 여기서 뺀다 — 없는 것과 이을 수는 없다.
        """
        title = 제목맞춤(title)
        out = set()
        for r in self.conn.execute("SELECT dst FROM links WHERE src = ?", (title,)):
            hit = self.resolve(r["dst"])
            if hit and hit != title:
                out.add(hit)
        names = self._names(title)
        holes = ",".join("?" * len(names))
        back = {r["src"] for r in self.conn.execute(
            f"SELECT src FROM links WHERE dst IN ({holes})", names) if r["src"] != title}
        return sorted(out | back)

    def backlinks(self, title: str) -> list[tuple[str, str]]:
        """**누가 나를 가리키나**와 그 문장.

        나가는 링크는 내가 적은 것이고, 들어오는 링크는 남이 나를 어떻게 쓰고 있는지다.
        AI가 쌓은 기록에서는 뒤쪽이 곧 맥락이라 따로 봐야 한다 — 섞어 놓으면
        "내가 적은 것"과 "나를 부른 것"이 구분이 안 된다.

        별칭으로 부른 것도 같이 잡는다. 문장은 그 링크가 실제로 놓인 줄을 준다.
        """
        title = 제목맞춤(title)
        names = set(self._names(title))
        holes = ",".join("?" * len(names))
        out = []
        # **색인에 있는 본문을 쓴다.** 가리킨 곳마다 파일을 다시 읽으면 항목 하나
        # 여는 데 0.7초가 든다(실제 기록으로 재봄). 색인은 파일에서 만든 것이라 같다.
        for r in self.conn.execute(
                f"SELECT DISTINCT l.src AS src, nt.body AS body FROM links l "
                f"JOIN notes nt ON nt.title = l.src WHERE l.dst IN ({holes})", tuple(names)):
            if r["src"] == title:
                continue
            line = ""
            for raw in (r["body"] or "").splitlines():
                if any(m.group(1).strip() in names for m in LINK_RE.finditer(raw)):
                    line = raw.strip()
                    break
            out.append((r["src"], line))
        return sorted(out)

    def 언급(self, title: str, k: int = 8) -> list[tuple[str, str]]:
        """**이름은 적었는데 링크로는 안 이은 글**과 그 줄. 옵시디언의 「연결 안 된 언급」이다.

        ★★ 오너 창고는 95%가 아무 데도 안 이어져 있다. 그런데 글 속에는 서로의 이름이
        **글자로는** 자주 나온다 — 그것이 곧 「여기 이으면 된다」는 자리다. 역링크만 보여 주면
        이 자리가 안 보인다. 두 글자 미만 제목은 안 본다(「VC」 같은 것은 어디에나 걸린다 — 그래도
        두 글자라 보긴 한다. 한 글자는 뜻이 없다).
        """
        title = 제목맞춤(title)
        이름들 = [n for n in self._names(title) if len(n) >= 2]
        if not 이름들:
            return []
        이미 = {src for src, _ in self.backlinks(title)} | {title}
        def 가둠(v: str) -> str:
            return "%" + v.replace("!", "!!").replace("%", "!%").replace("_", "!_") + "%"
        조건 = " OR ".join("body LIKE ? ESCAPE '!'" for _ in 이름들)
        out = []
        for r in self.conn.execute(
                f"SELECT title, body FROM notes WHERE ({조건}) ORDER BY mtime DESC LIMIT 200",
                [가둠(n) for n in 이름들]):
            if r["title"] in 이미:
                continue
            줄 = next((l.strip() for l in (r["body"] or "").splitlines()
                      if any(n in l for n in 이름들)), "")
            out.append((r["title"], 줄[:160]))
            if len(out) >= k:
                break
        return out

    def 외딴것수(self) -> int:
        """외딴 글이 모두 몇 장인가. **목록만 주면 「서른 개야」라고 거짓말한다** —
        오너 창고를 재 보니 2836장 중 2700장(95%)이 외딴이었다."""
        return self.conn.execute(
            "SELECT count(*) FROM notes n WHERE n.pinned = 0"
            " AND NOT EXISTS (SELECT 1 FROM links l WHERE l.src = n.title OR l.dst = n.title)"
        ).fetchone()[0]

    def 외딴것(self, k: int = 30) -> list[str]:
        """아무 데도 안 이어진 글들. **옵시디언의 「고아 노트」** 자리다.

        이 창고는 AI 가 3천 장을 붓는 물건이라 외딴 글이 쌓이기 쉽다 —
        이어지지 않은 글은 그물에서 빠져 뜻 검색 말고는 닿을 길이 없다.
        고정한 것은 뺀다(사람이 일부러 세워 둔 것이다).
        """
        return [r[0] for r in self.conn.execute(
            "SELECT n.title FROM notes n WHERE n.pinned = 0"
            " AND NOT EXISTS (SELECT 1 FROM links l WHERE l.src = n.title OR l.dst = n.title)"
            " AND NOT EXISTS (SELECT 1 FROM aliases a JOIN links l2 ON l2.dst = a.alias"
            "                 WHERE a.title = n.title)"
            " ORDER BY n.mtime DESC LIMIT ?", (k,))]

    def unresolved(self) -> list[tuple[str, int]]:
        """아무 데도 안 닿는 링크와 그것을 가리키는 항목 수.

        **한 번의 질의로 끝낸다.** 예전엔 링크를 하나씩 돌며 행마다 또 질의했는데,
        항목 2만 개에서 질의가 4만 번이 되어 화면이 통째로 멈췄다(스택을 떠 보니 여기서
        막혀 있었다). 갱신할 때마다 도는 자리라 반드시 한 방이어야 한다.
        """
        rows = self.conn.execute(
            "SELECT l.dst AS name, count(DISTINCT l.src) AS n FROM links l "
            "LEFT JOIN notes nt ON nt.title = l.dst "
            "LEFT JOIN aliases a ON a.alias = l.dst "
            "WHERE nt.title IS NULL AND a.alias IS NULL "
            "GROUP BY l.dst ORDER BY n DESC, l.dst")
        # 질의는 제목·별칭만 본다. 경로로 건 링크(`[[폴더/노트]]`)는 여기 후보로 남으므로
        # **후보에 대해서만** 한 번 더 확인한다 — 후보는 몇 개뿐이라 값이 안 든다.
        return [(r["name"], r["n"]) for r in rows if self.resolve(r["name"]) is None]

    def by_year(self) -> list[tuple[str, int]]:
        """해마다 항목이 몇 개인지. 최근이 앞이다.

        20년치가 쌓이면 "작년 그 프로젝트"가 흔한 물음이 된다. 글자로만 찾으면 그때
        자기가 쓴 표현을 기억해야 하는데, **시간은 사람이 확실히 기억하는 축**이다.
        """
        rows = self.conn.execute(
            "SELECT substr(created, 1, 4) AS y, count(*) AS n FROM notes "
            "GROUP BY y ORDER BY y DESC")
        return [(r["y"], r["n"]) for r in rows if r["y"]]

    def in_year(self, year: str) -> list[tuple[str, str]]:
        """그 해에 처음 적은 항목들. 늦게 적은 것이 앞이다."""
        rows = self.conn.execute(
            "SELECT title, body FROM notes WHERE substr(created, 1, 4) = ? "
            "ORDER BY created DESC", (year,))
        return [(r["title"], r["body"]) for r in rows]

    def written_when(self, when: str) -> list[tuple[str, str, str]]:
        """그 무렵 손댄 항목들. "어제 쓴 것" 같은 지시가 쓴다.

        **만든 때가 아니라 고친 때로 본다.** 사람이 "어제 쓴 것"이라고 할 때는
        어제 손댄 것을 말한다 — 3년 전에 만들어 어제 고친 글도 어제 쓴 것이다.
        """
        now = time.time()
        day = 86400.0
        # 오늘 0시를 기준으로 잡는다. "어제"가 24시간 전이 아니라 어제 하루여야 한다.
        midnight = now - (now - time.timezone) % day
        spans = {
            "오늘": (midnight, now + day),
            "어제": (midnight - day, midnight),
            "그저께": (midnight - 2 * day, midnight - day),
            "이번주": (midnight - day * ((int((now - time.timezone) // day) + 4) % 7), now + day),
            "지난주": (midnight - day * 14, midnight),
            "이번달": (midnight - day * 30, now + day),
            "지난달": (midnight - day * 60, midnight - day * 30),
        }
        span = spans.get(when.replace(" ", ""))
        if span is None:
            return []
        rows = self.conn.execute(
            "SELECT title, body, path FROM notes WHERE mtime >= ? AND mtime < ? "
            "ORDER BY mtime DESC LIMIT 40", span).fetchall()
        return [(r["title"], r["body"], r["path"]) for r in rows]

    def by_tag(self, tag: str) -> list[str]:
        """태그가 붙은 항목들. 하위 태그(#할일/오늘)는 상위(#할일)로도 걸린다."""
        return sorted(r["title"] for r in self.conn.execute(
            "SELECT title FROM tags WHERE tag = ? OR tag LIKE ?", (tag, f"{tag}/%")))

    def all_tags(self) -> list[tuple[str, int]]:
        return [(r["tag"], r["n"]) for r in self.conn.execute(
            "SELECT tag, count(*) AS n FROM tags GROUP BY tag ORDER BY n DESC, tag")]

    def working_set(self, limit: int, keep: set[str] | None = None) -> list[str]:
        """화면에 올릴 항목을 고른다. **고정 → 최근 본 것 → 최근 적은 것** 순이다.

        20년치를 한 화면에 다 그릴 수는 없다. 물리 계산이 항목 수에 비례하므로
        수천 개를 올리면 창이 굳는다(4000개에 한 걸음 0.53초, 실측).

        `keep`은 반드시 넣어야 하는 것들이다 — 방금 찾은 것이 잘려 나가면 안 된다.
        """
        # 없는 이름을 받으면 조용히 무시한다 — 지워진 항목을 붙들고 있을 수 있다.
        must = {t for t in (keep or ()) if self.read(t) is not None}
        rows = self.conn.execute(
            "SELECT title FROM notes ORDER BY pinned DESC, "
            "COALESCE(used_at, 0) DESC, created DESC")
        picked = list(must)
        for r in rows:
            if len(picked) >= limit:
                break
            if r["title"] not in must:
                picked.append(r["title"])
        return picked

    def kinds_of(self, titles) -> dict[str, str]:
        """고른 것들의 종류만. 전부 끌어오면 항목 2만 개에서 그것만 0.1초다."""
        names = list(titles)
        if not names:
            return {}
        holes = ",".join("?" * len(names))
        return {r["title"]: r["kind"] for r in self.conn.execute(
            f"SELECT title, kind FROM notes WHERE title IN ({holes})", names)}

    # 뜻으로 이을 때의 문턱. 찾을 때(`NEAR_FLOOR`)보다 훨씬 높다 — 찾기는 「없는 것보다
    # 낫다」로 받아도 되지만, **이음선은 틀리면 거짓 관계를 그려 놓는 것**이라 더 엄하다.
    # **서로를 1등으로 꼽을 때만 잇는다.** 문턱도 배수도 없다.
    #
    # 처음엔 「가장 가까운 하나」를 늘 이었다 — 그러면 짝이 없는 글도 아무하고나 엮인다
    # (「겨울 타이어 ↔ 등산 스틱」). 다음엔 「그 항목 안에서 도드라지나」로 걸러 봤는데,
    # 찍어낸 무리가 400개 깔린 자리에서는 **하나도 안 걸러졌다**(실측 0/4) — 무리가
    # 평균을 낮게 깔아 무엇이든 도드라져 보인다.
    #
    # 맞짝은 그 둘에 안 흔들린다. 자리가 크든 작든, 잡음이 많든 적든 뜻이 같다:
    # **둘이 서로를 가장 가깝다고 볼 때만 이어져 있다.** 같은 자리에서 재니
    # 억지 이음선 넷 중 둘을 옳게 비웠고(0/4 에서), 맞는 짝은 그대로 남았다.
    #
    # 덤으로 선이 **양쪽 말이 같아진다** — 한쪽에서만 보이는 이음선이 없다.
    def kin(self, titles, 맞짝만: bool = True) -> dict[str, list[str]]:
        """**손으로 안 이어도 뜻으로 이어 준다.** `{제목: [맞짝]}`.

        닷새를 실제로 쓴 자리에서 항목 528개에 손으로 적은 이음선이 **둘**이었다.
        그 둘도 사람이 하루 만에 적은 것이고, 그 뒤 수백 번 쓰고 고치는 동안 새로 이은
        것은 **하나도 없다.** 「알면서도 안 한다」는 것이 「몰라서 못 한다」보다 무겁다 —
        그러니 잇는 일을 사람에게 맡기면 그래프는 영영 점 뿌린 판으로 남는다.

        **파일에는 아무것도 안 쓴다.** 벡터에서 그때그때 셈한다 — 잘못 이어도 기록이
        더러워지지 않고, 모델을 바꾸면 이음선도 저절로 따라온다.

        **그래프 선과 카드 줄은 다르게 다룬다.**

        - 그래프 선(`맞짝만=True`)은 **양쪽이 동의한 것만.** 선은 「이 둘은 이어져 있다」는
          단언이고, 화면을 어지럽히며, 한쪽만 보는 관계를 선으로 그으면 반대쪽에서 볼 때
          말이 안 맞는다.
        - 카드의 「비슷한 것」(`맞짝만=False`)은 **내가 꼽은 1등이면 된다.** 그건 단언이
          아니라 **내가 지금 밟을 수 있는 길**이다. 한쪽만 알아보는 관계도 있다 —
          「조사 어긋나감」에게 「맞춤법 점검」은 분명한 이웃인데 그 반대는 아니었고,
          맞짝만 고집하니 **그래프의 값을 증명했던 바로 그 항목이 다시 외딴 점**이 됐다.
          갈 길이 하나도 없는 것이 어중간한 길 하나보다 나쁘다.
        """
        got = self._vectors()
        if got is None:
            return {}
        import numpy as np

        names, mat, _ = got
        where = {t: i for i, t in enumerate(names)}
        고른 = [(t, where[t]) for t in dict.fromkeys(titles) if t in where]
        if not 고른:
            return {}

        def 가장가까운(자리: list[int]) -> list[int]:
            """줄줄이 하나씩 곱하지 않는다 — 2만 개에서 그것만 몇 초다.

            **제목 벡터는 안 쓴다.** 찾을 때는 제목 쪽도 같이 보는 것이 낫지만(사람이
            치는 말이 제목에 있는 경우가 많다), **이웃을 고를 때는 해롭다.** 짧은 제목은
            뜻 공간에서 아무거나에 가까워서, 본문이 「한 줄」뿐인 시험용 항목이 진짜 글의
            이웃 자리를 통째로 뺏는다 — 실사용 자리에서 쓰레기 셋이 두 항목 모두의
            1·2·3등이었다(제목 0.93 대 카드 0.85). 카드만 보면 그 자리에 제대로 된 것이
            돌아온다: 「맞춤법 점검 → 조사 어긋나감」.
            """
            쪽 = mat @ mat[자리].T                                     # (전체, 고른 수)
            쪽[자리, range(len(자리))] = -1.0        # 자기 자신은 뺀다
            return [int(i) for i in np.argmax(쪽, axis=0)]

        이웃 = 가장가까운([i for _, i in 고른])
        # ★★ **혼자면 이웃이 없다.** 자기 자신을 뺀 자리에 아무도 안 남으면
        # `argmax` 가 **그 자기 자신을 도로 집는다** — 항목 한 장짜리 새 창고에서
        # 「VC ↔ VC」라는 이음선이 나왔다(시험 쪽이 잡았다). 없는 것이 옳다.
        if not 맞짝만:
            return {t: ([names[j]] if j != i else []) for (t, i), j in zip(고른, 이웃)}
        # **상대도 나를 1등으로 꼽는가.** 한 번 더 곱해서 되묻는다.
        # 중복을 지운 목록으로 물어야 하고, 짝지을 때도 **그 목록**과 짝지어야 한다 —
        # 중복이 있는 쪽과 없는 쪽을 zip 하면 엉뚱한 답이 붙는다(그래서 한쪽만 이어졌다).
        한번씩 = list(dict.fromkeys(이웃))
        되물음 = dict(zip(한번씩, 가장가까운(한번씩)))
        out: dict[str, list[str]] = {}
        for (t, i), j in zip(고른, 이웃):
            out[t] = [names[j]] if (j != i and 되물음.get(j) == i) else []
        return out

    def subgraph(self, titles) -> dict[str, list[str]]:
        """고른 것들끼리의 연결만. 밖으로 나가는 링크는 뺀다 — 안 보이는 점에
        선이 걸리면 그래프가 끊긴 실을 매단 꼴이 된다.
        """
        inside = set(titles)
        return {t: [n for n in self.neighbors(t) if n in inside] for t in inside}

    def graph(self) -> dict[str, list[str]]:
        """빈 페이지에서 VC 하나로 시작해 자라는 그 그래프. **이은 것만** 준다.

        ★★ **이음선이 없는 마디는 정보가 0인데 값은 든다.** 예전에는 모든 항목을
        `제목: []` 꼴로 실어 보냈다 — 오너 창고(2794장)에서 재 보니 **98,425자**가
        나가는데 그중 이음선이 있는 마디가 **하나도 없었다.** AI 가 그걸 받아 읽으면
        38,000토큰을 태우고 아무것도 못 얻는다(오너 지시 2026-09-12: 크레딧이 곧 성능이다).
        빈 것을 빼니 **13자**가 됐다.

        제목 목록이 필요하면 그건 그래프가 할 일이 아니다 — 찾기로 묻는다.
        """
        나온 = {}
        for r in self.conn.execute("SELECT title FROM notes ORDER BY title"):
            이웃 = self.neighbors(r["title"])
            if 이웃:
                나온[r["title"]] = 이웃
        return 나온


def _self_check() -> None:
    import tempfile

    # ★★ **같은 이름을 두 번 정의하면 앞엣것은 죽는다 — 그런데 고칠 때는 앞엣것이 먼저 보인다.**
    #   실제로 `NARROW` 를 앞에서 고쳤는데 뒤엣것이 이겨 **조용히 안 먹었다.**
    #   되돌려 터뜨려 보고서야 알았다. 이 파일은 한때 90~330줄이 통째로 되풀이됐다.
    #   (구운 판에는 소스가 없다 — 그때는 건너뛴다.)
    try:
        본문 = Path(__file__).read_text(encoding="utf-8")
    except OSError:
        본문 = ""
    if 본문:
        import collections

        # `이름(` 은 **부르는 것**이라 정의가 아니다 — `def`/`class` 와 맨 왼쪽 대입만 센다.
        # `_` 는 버리는 이름이라 여러 번 나와도 된다. 두 글자 이상만 본다.
        선언 = [이름 for 이름 in
               (re.findall(r"^(?:class|def)\s+([A-Za-z_][A-Za-z_0-9]*)", 본문, re.M)
                + re.findall(r"^([A-Z][A-Z_0-9]+)\s*=[^=]", 본문, re.M))
               if 이름.strip("_")]
        겹친 = sorted(이름 for 이름, 수 in collections.Counter(선언).items() if 수 > 1)
        assert not 겹친, f"같은 이름을 두 번 정의했다 — 앞엣것은 죽은 코드다: {겹친}"

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "notes"
        n = Notes(root)

        n.write(Note(title="VC", body="시작 항목. [[카페 단골]]을 안다.", kind="agent"))
        n.write(Note(title="카페 단골", body="난 아이스만 마신다.", kind="preference", pinned=True))

        got = n.read("카페 단골")
        assert got is not None and got.pinned is True and got.kind == "preference"
        assert n.read("없는항목") is None

        assert n.neighbors("카페 단골") == ["VC"], "역링크가 안 잡힌다"
        assert n.neighbors("VC") == ["카페 단골"]

        assert [r["title"] for r in n.search("아이스")] == ["카페 단골"]
        # 반환된 행은 증가 이전 값이므로 인덱스에서 다시 읽어 확인한다.
        counted = n.conn.execute(
            "SELECT use_count FROM notes WHERE title = ?", ("카페 단골",)
        ).fetchone()["use_count"]
        assert counted == 1, f"조회 횟수가 안 오른다: {counted}"

        # 고정된 항목이 먼저 나온다.
        n.write(Note(title="최근 메모", body="아이스 아메리카노 봤음"))
        assert n.search("아이스")[0]["title"] == "카페 단골"

        # ★★ **AI 가 부어 넣은 글 안의 `[[ ]]` 는 「사람이 이은 것」이 아니다.**
        # 흡수한 보고서가 `[[다른이름]]` 을 **예시로 인용**만 해도 굳은 선이 생겼다 —
        # 상태줄의 「적은 것」이 2에서 4로 늘었는데 사람은 아무것도 안 이었다.
        # 실제로 그 여섯 중 넷은 **있지도 않은 항목**을 가리키고 있었다.
        with tempfile.TemporaryDirectory() as 딴자리:
            m = Notes(Path(딴자리) / "notes", str(Path(딴자리) / "i.db"))
            m.write(Note(title="문지기가 쓴 것", body="예시로 [[다른이름]] 을 쳐 보니",
                         kind="일", extra={"지은이": "문지기", "출처": "a.md"}))
            m.write(Note(title="사람이 쓴 것", body="이건 [[VC]] 를 가리킨다", kind="일"))
            # ★ **약속이 바뀌었다.** 예전엔 흡수 글의 `[[ ]]` 를 **아예 안 넣었는데**,
            #   실제 자료가 사실상 전부 흡수분이라 **그물이 통째로 비었다**
            #   (3142장에 이음 0). 이제 **안 넣는 대신 갈라서 넣는다** —
            #   진한 선 흐림=0, 흐린 선 흐림=1. 「사람이 이은 것」의 뜻은 칸이 지킨다.
            걸린 = {(r["src"], r["dst"], r["흐림"]) for r in
                    m.conn.execute("SELECT src, dst, 흐림 FROM links")}
            assert ("사람이 쓴 것", "VC", 0) in 걸린, 걸린
            assert ("문지기가 쓴 것", "다른이름", 1) in 걸린, 걸린
            # 파일에서 다시 읽어도 마찬가지다 — 색인을 다시 쌓아도 안 들어온다.
            m.conn.execute("DELETE FROM notes")
            m.conn.execute("DELETE FROM links")
            m.conn.commit()
            m.reindex()
            다시 = {(r["src"], r["dst"], r["흐림"]) for r in
                    m.conn.execute("SELECT src, dst, 흐림 FROM links")}
            assert 다시 == 걸린, (다시, 걸린)
            m.conn.close()

        # 사용자가 옵시디언에서 손으로 만든 파일도 받아들인다.
        (root / "손으로 쓴 것.md").write_text("프론트매터 없음 [[VC]]", encoding="utf-8")  # 평면에 손으로
        assert n.reindex() == 1
        assert n.read("손으로 쓴 것").kind == "note"
        assert "손으로 쓴 것" in n.neighbors("VC")

        # 인덱스는 언제든 파일에서 다시 만들 수 있다 — 복구 수단이 항상 있다.
        n.conn.execute("DELETE FROM notes")
        n.conn.execute("DELETE FROM links")
        n.conn.commit()
        assert n.reindex() == 4
        # ★ 그래프는 **이은 것만** 준다. 이음선 없는 마디는 정보가 0인데 값은 든다 —
        #   오너 창고 2794장에서 98,425자가 나가고 그중 이은 마디가 하나도 없었다.
        이은것 = n.graph()
        assert all(이은것.values()), f"이음선 없는 마디가 실려 온다: {이은것}"
        assert "VC" in 이은것 and "손으로 쓴 것" in 이은것["VC"], f"이은 것이 빠졌다: {이은것}"
        assert len(이은것) < 4, f"빈 마디까지 센다 ({len(이은것)}개)"

        # 지우면 태그·별칭 색인에서도 같이 사라진다. 하나만 남아도 유령이 잡힌다.
        n.write(Note(title="지울것", body="#유령태그", aliases=["유령별칭"]))
        assert n.by_tag("유령태그") == ["지울것"] and n.resolve("유령별칭") == "지울것"
        n.delete("지울것")
        assert n.by_tag("유령태그") == [], "지웠는데 태그가 남았다"
        assert n.resolve("유령별칭") is None, "지웠는데 별칭이 남았다"

        # 파일을 지우면 인덱스에서도 사라진다(결정 22: 삭제 가능).
        assert n.delete("최근 메모") is True
        assert n.delete("최근 메모") is False
        assert len(n.graph()) == 3

        # 파일명에 못 쓰는 글자가 있어도 저장된다.
        p = n.write(Note(title="계약서: 2026/08 검토", body="독소조항 확인"))
        assert p.exists() and ":" not in p.name and "/" not in p.name

        # 이름을 바꾸면 가리키던 링크도 같이 옮겨진다. 안 그러면 연결이 끊긴다.
        assert n.rename("VC", "불칸")
        assert n.read("VC") is None and n.read("불칸") is not None
        assert n.neighbors("카페 단골") == ["불칸"], "링크가 옛 이름을 가리킨다"
        assert not n.rename("없는것", "아무거나"), "없는 항목을 옮겼다"
        n.write(Note(title="이미있음", body="", kind="note"))
        assert not n.rename("불칸", "이미있음"), "덮어썼다"
        # ★★ **링크에는 네 꼴이 있다.** 글자로만 `[[옛것]]` 을 바꾸면 나머지 셋이
        #   허공을 가리킨다 — 그래프가 반쯤 끊긴 채로 남고 끊긴 줄도 모른다.
        n.write(Note(title="옮길 것", body="몸"))
        n.write(Note(title="가리키는 데",
                     body="[[옮길 것]] · [[옮길 것|보일 글]] · ![[옮길 것#머리]] · [[옮길 것#칸]] · [[딴 것]]"))
        assert n.rename("옮길 것", "옮긴 것")
        바뀐 = n.read("가리키는 데").body
        assert "옮길 것" not in 바뀐, f"옛 이름이 남았다: {바뀐}"
        for 꼴 in ("[[옮긴 것]]", "[[옮긴 것|보일 글]]", "![[옮긴 것#머리]]", "[[옮긴 것#칸]]"):
            assert 꼴 in 바뀐, f"{꼴} 꼴을 안 고쳤다: {바뀐}"
        assert "[[딴 것]]" in 바뀐, "남의 링크까지 건드렸다"

    # --- 링크 체계: 태그·별칭·제목링크·미해결 ---
    with tempfile.TemporaryDirectory() as tmp:
        n = Notes(Path(tmp) / "notes")
        n.write(Note(title="회사", body="9시 출근. #장소 #할일/출근", aliases=["직장", "사무실"]))
        n.write(Note(title="아침", body="[[직장]]까지 [[지하철#2호선]]. #할일/출근"))

        # 별칭으로 건 링크도 실제 항목으로 이어진다. 안 그러면 그래프가 두 배로 부푼다.
        assert n.resolve("직장") == "회사" and n.resolve("사무실") == "회사"
        assert n.resolve("회사") == "회사"
        assert n.resolve("없는이름") is None
        assert n.neighbors("아침") == ["회사"], n.neighbors("아침")
        assert n.neighbors("회사") == ["아침"], "별칭으로 온 역링크를 놓친다"
        # ★ **열기도 별칭으로 돼야 한다.** 링크만 닿고 `read` 는 404 였다 —
        #   AI 꺼내기 2단이 그 길을 쓰므로 별칭 붙은 글은 영영 못 펼쳤다(옵시디언은 열린다).
        assert (n.read("회사") or Note(title="", body="")).title == "회사"
        열린것 = n.read("직장")
        assert 열린것 is not None and 열린것.title == "회사", "별칭으로 글을 못 연다"

        # 누가 나를 가리키나 — 그 문장까지 같이 온다.
        backs = n.backlinks("회사")
        assert backs == [("아침", "[[직장]]까지 [[지하철#2호선]]. #할일/출근")], backs
        assert n.backlinks("아침") == [], "가리킨 곳이 없는데 뭔가 나온다"

        # 제목 링크의 소제목이 남아 있어야 그 자리로 데려갈 수 있다.
        head = n.conn.execute(
            "SELECT heading FROM links WHERE src = ? AND dst = ?", ("아침", "지하철")).fetchone()
        assert head["heading"] == "2호선", head["heading"]

        # 아직 없는 항목을 가리키는 링크 — 사람이 쓰다 만 자리다.
        assert n.unresolved() == [("지하철", 1)], n.unresolved()
        n.write(Note(title="지하철", body="2호선 탄다."))
        assert n.unresolved() == [], "항목이 생겼는데도 미해결로 남는다"

        # 끼워 보기. 링크와 같은 꼴이라 연결로도 잡힌다.
        n.write(Note(title="보고서", body=chr(10).join(
            ["## 7월", "지난달 내용", "", "## 8월 정산", "정산 끝", "### 세부", "잔금"])))
        n.write(Note(title="요약", body="이번 달: ![[보고서#8월 정산]] 참고"))
        assert n.read("요약").embeds() == [("보고서", "8월 정산")]
        assert "보고서" in n.neighbors("요약"), "끼운 것도 연결이어야 한다"
        cut = section(n.read("보고서").body, "8월 정산")
        assert "정산 끝" in cut and "잔금" in cut, cut
        assert "지난달" not in cut, "다른 토막까지 끌고 왔다"
        assert section(n.read("보고서").body, "없는 소제목") == ""

        # ★★ **긴 제목을 자를 때 앞부분이 같으면 한 글이 다른 글을 조용히 덮었다.**
        #   아무 말도 안 나오고 먼저 쓴 것이 사라진다 — 창고가 할 수 있는 가장 나쁜 일이다.
        긴가 = "길" * 300 + "가"
        긴나 = "길" * 300 + "나"
        n.write(Note(title=긴가, body="첫째 글"))
        n.write(Note(title=긴나, body="둘째 글"))
        assert n.read(긴가).body.startswith("첫째"), "긴 제목이 서로를 덮는다"
        assert n.read(긴나).body.startswith("둘째"), "긴 제목이 서로를 덮는다"
        assert safe_title("짧은 제목") == "짧은 제목", "안 자르는 제목까지 이름을 바꿨다 — 링크가 끊긴다"
        # ★★ **대소문자만 다른 제목도 서로를 덮었다.** 윈도우 파일 이름은 대소문자를
        #   안 가린다 — 둘 다 읽으면 나중 몸이 나왔다. 아무 말도 안 나온다.
        n.write(Note(title="Alpha", body="큰 글"))
        n.write(Note(title="alpha", body="작은 글"))
        assert n.read("Alpha").body.startswith("큰"), "대소문자만 다른 제목이 서로를 덮는다"
        assert n.read("alpha").body.startswith("작은"), "대소문자만 다른 제목이 서로를 덮는다"
        # ★★ **그 막이가 쓰기를 O(장수)로 만들면 안 된다.** 처음엔 새 글마다 폴더를 훑어
        #   2만 장 시험에서 한 장 쓰기가 17ms → 785ms(45배)가 됐다. `exists()` 로 먼저 거른다.
        import time as _t

        많이 = n.root / "2026" / "09"
        많이.mkdir(parents=True, exist_ok=True)
        for _i in range(300):
            (많이 / f"채움 {_i}.md").write_text("채우는 글", encoding="utf-8")
        t0 = _t.perf_counter()
        for _i in range(20):
            n.path_of(f"아주 새 글 {_i}")
        든시간 = (_t.perf_counter() - t0) / 20
        assert 든시간 < 0.01, f"새 글 자리 찾기가 폴더를 훑는다: 한 번에 {든시간 * 1000:.1f}ms"
        # ★★ **밖에서 지운 글이 검색에 계속 걸렸다.** 옵시디언·탐색기로 지우면 색인은
        #   다음 훑기 전까지 그대로라, 검색은 주는데 펼치면 없다 — AI 는 찾은 줄 알고
        #   2단을 부르고 800자를 버린다. 내놓기 직전에 확인하고 색인에서도 지운다.
        n.write(Note(title="사라질 글", body="곧 없어질 몸이다"))
        next(n.root.rglob("사라질 글.md")).unlink()
        assert n.search("없어질") == [], "밖에서 지운 글이 아직 걸린다"
        assert n.search("없어질") == [], "한 번 빼고 색인에 그대로 뒀다 — 다음에 또 걸린다"
        # ★ **「이것 아니면 저것」** — 옵시디언은 `TODO OR FIXME` 가 되는데 우리는 0건이었다.
        n.write(Note(title="할일 가", body="TODO 고치기"))
        n.write(Note(title="할일 나", body="FIXME 급함"))
        assert sorted(r["title"] for r in n.search("TODO OR FIXME")) == ["할일 가", "할일 나"],             "OR 로 묶은 물음이 하나도 안 걸린다"
        assert sorted(r["title"] for r in n.search("TODO 또는 FIXME")) == ["할일 가", "할일 나"],             "한글 「또는」이 안 먹는다"
        assert [r["title"] for r in n.search("TODO")] == ["할일 가"], "OR 없이도 그대로여야 한다"
        # ★ **제목만 보기**(옵시디언 `file:`). 본문에 그 말이 여러 번 나오는 글이
        #   제목이 그 말인 글을 덮는 일이 흔하다 — 그때 이것 하나로 갈린다.
        n.write(Note(title="회의록 2026", body="본문에는 그 말이 없다"))
        n.write(Note(title="딴 글", body="회의록 회의록 회의록"))
        assert [r["title"] for r in n.search("title:회의록")] == ["회의록 2026"], "제목만 좁히기가 안 된다"
        assert [r["title"] for r in n.search("제목:회의록")] == ["회의록 2026"], "한글 이름이 안 먹는다"
        assert [r["title"] for r in n.search("-title:회의록 회의록")] == ["딴 글"], "제목 빼기가 안 된다"

        # ★ **블록 참조** — 소제목이 없는 긴 글에서 한 자리를 가리키는 유일한 길이다.
        #   오너 창고는 1000자 넘는 글 199장 중 소제목이 있는 것이 7장뿐이라 값이 크다.
        #   옵시디언과 같은 꼴(`[[글#^이름]]`)이라 그쪽에서 적은 것이 그대로 닿는다.
        블록글 = chr(10).join(["첫 문단이다.", "두 줄째다. ^앞칸", "",
                             "- 첫 항목", "- 둘째 항목 ^목록칸", "- 셋째 항목", "",
                             "수식은 2^10 이다."])
        n.write(Note(title="블록 시험", body=블록글))
        몸 = n.read("블록 시험").body
        assert block(몸, "^앞칸") == "첫 문단이다." + chr(10) + "두 줄째다.", block(몸, "^앞칸")
        assert block(몸, "목록칸") == "- 둘째 항목", "목록은 그 줄만 줘야 한다"
        assert block(몸, "없는이름") == ""
        assert block(몸, "10") == "", "글 가운데의 ^ 를 블록 이름으로 읽었다 (2^10)"
        assert blocks(몸) == ["앞칸", "목록칸"], blocks(몸)
        # 부르는 쪽을 안 고쳐도 되게 `section` 이 갈라 보낸다.
        assert section(몸, "^앞칸") == block(몸, "^앞칸"), "section 이 블록을 안 넘겨준다"
        # 링크로도 닿아야 한다 — 이름에 한글이 들어가도 마찬가지다.
        n.write(Note(title="블록 부름", body="여기 봐: [[블록 시험#^목록칸]]"))
        assert "블록 시험" in n.neighbors("블록 부름"), "블록 링크가 연결로 안 잡힌다"

        # 화면에 올릴 것 고르기 — 20년치를 다 그릴 수는 없다.
        n.write(Note(title="고정된 것", body="", pinned=True))
        picked = n.working_set(3, keep={"보고서"})
        assert "보고서" in picked, "반드시 넣으랬는데 잘렸다"
        assert len(picked) == 3
        assert n.working_set(2)[0] == "고정된 것", "고정한 게 먼저 안 온다"

        # ★★ **옵시디언이 쓰는 앞머리 꼴을 받아야 한다.** 태그·별칭을 블록 목록으로 적는데
        #   한 줄씩 `k: v` 로만 읽던 때는 `tags: ""` 가 되어, **다시 쓸 때 사람이 적은 태그가
        #   통째로 사라졌다.** 별칭도 죽어 옵시디언 별칭으로는 글이 안 열렸다.
        #   같은 볼트를 두 도구가 나눠 보는데 한쪽만 안 보이면 사람은 「사라졌다」고 느낀다.
        옵글 = ("---" + chr(10) + "tags:" + chr(10) + "  - 옵시태그" + chr(10)
                + "  - 프로젝트/VC" + chr(10) + "aliases:" + chr(10) + "  - 딴이름" + chr(10)
                + "---" + chr(10) + chr(10) + "내용이다. #직접태그" + chr(10))
        (n.root / "옵시디언 글.md").write_text(옵글, encoding="utf-8")
        n.reindex()
        읽은 = n.read("옵시디언 글")
        assert 읽은 is not None and 읽은.extra.get("tags") == ["옵시태그", "프로젝트/VC"],             f"블록 목록 앞머리를 못 읽는다: {읽은.extra if 읽은 else None}"
        assert 읽은.aliases == ["딴이름"], f"옵시디언 별칭을 못 읽는다: {읽은.aliases}"
        assert n.read("딴이름") is not None, "옵시디언 별칭으로 글이 안 열린다"
        assert set(읽은.tags()) == {"옵시태그", "프로젝트/VC", "직접태그"}, 읽은.tags()
        assert "옵시디언 글" in [r["title"] for r in n.search("tag:프로젝트")], "앞머리 태그로 못 찾는다"
        # 다시 써도 사람이 적은 것이 남아야 한다.
        n.write(Note(title="옵시디언 글", body=읽은.body + "덧", aliases=읽은.aliases, extra=읽은.extra))
        글 = (n.root / "옵시디언 글.md").read_text(encoding="utf-8")
        assert "옵시태그" in 글 and "딴이름" in 글, f"다시 쓰면서 사람이 적은 것을 지웠다: {글[:120]}"

        # ★★ **우리가 못 읽는 앞머리 꼴도 지우지는 않는다.** 옵시디언·플러그인이 쓰는
        #   중첩 사전(`obsidian:` 아래 들여쓴 줄)·여러 줄 글(`note: >`)·한 줄 대괄호 목록이
        #   있는데, 전에는 앞 둘이 `""` 로 뭉개져 **다시 쓰는 순간 사라졌다.**
        #   원본이 원본이라는 규칙은 우리가 못 읽는 자리에도 같다.
        깊은앞 = ("---" + chr(10) + "obsidian:" + chr(10) + "  plugin: dataview" + chr(10)
                 + "note: >" + chr(10) + "  여러 줄로" + chr(10) + "  이어 적는다" + chr(10)
                 + "tags: [묶음태그, 둘째]" + chr(10) + "---" + chr(10) + chr(10) + "몸" + chr(10))
        (n.root / "깊은 앞머리.md").write_text(깊은앞, encoding="utf-8")
        n.reindex()
        깊 = n.read("깊은 앞머리")
        assert 깊.tags() == ["묶음태그", "둘째"], f"한 줄 대괄호 목록에서 대괄호가 샌다: {깊.tags()}"
        n.write(Note(title="깊은 앞머리", body=깊.body + "덧", extra=깊.extra))
        다시 = (n.root / "깊은 앞머리.md").read_text(encoding="utf-8")
        assert "plugin: dataview" in 다시, f"중첩 사전이 사라졌다: {다시[:150]}"
        assert "이어 적는다" in 다시, f"여러 줄 글이 사라졌다: {다시[:150]}"
        assert "note: >" in 다시, f"여러 줄 표시(>)가 사라졌다: {다시[:150]}"

        # ★★ **맥(NFD) 한글.** 맥 파일 이름은 「회의록」을 풀어 적어 윈도우에서 친 글자와 다르다 —
        #   그 글이 안 열리고, `[[회의록]]` 이 파일이 있는데도 「아직 없는 것」으로 셌다.
        import unicodedata as _u

        맥이름 = _u.normalize("NFD", "맥회의록")
        (n.root / f"{맥이름}.md").write_text(_u.normalize("NFD", "맥에서 적은 몸"), encoding="utf-8")
        (n.root / "맥 가리킴.md").write_text("[[맥회의록]] 본다", encoding="utf-8")
        n.reindex()
        assert n.read("맥회의록") is not None, "맥에서 온 한글 제목 글이 안 열린다"
        assert "맥회의록" in [r["title"] for r in n.search("맥에서")], "맥에서 온 한글 본문이 안 찾힌다"
        assert "맥회의록" not in dict(n.unresolved()), "파일이 있는데 링크를 「아직 없는 것」으로 센다"

        # ★★ **파일에 못 쓰는 글자가 든 제목.** 전에는 `-` 로 바꿔 「질문? 답」 링크가 끊겼고,
        #   「질문? 답」과 「질문: 답」이 같은 파일로 서로 덮였다.
        n.write(Note(title="질문? 답", body="물음표 몸"))
        n.write(Note(title="질문: 답", body="쌍점 몸"))
        assert n.read("질문? 답").body.startswith("물음표"), "못 쓰는 글자 제목끼리 서로 덮는다"
        assert n.read("질문: 답").body.startswith("쌍점"), "못 쓰는 글자 제목끼리 서로 덮는다"
        n.write(Note(title="물음 가리킴", body="[[질문? 답]] 본다"))
        assert "질문？ 답" not in dict(n.unresolved()) and "질문? 답" not in dict(n.unresolved()),             f"못 쓰는 글자 제목으로 건 링크가 끊겼다: {n.unresolved()}"
        assert "물음 가리킴" in [t for t, _ in n.backlinks("질문? 답")], "역링크가 안 잡힌다"
        # 옛 판이 `-` 로 저장한 파일도 그 제목으로 열려야 한다.
        (n.root / "옛- 제목.md").write_text("옛 판이 쓴 몸", encoding="utf-8")
        n.reindex()
        assert (n.read("옛? 제목") or Note(title="", body="")).body.startswith("옛 판"),             "옛 판이 `-` 로 저장한 글이 원래 제목으로 안 열린다"

        # ★★ **연결 안 된 언급** — 이름은 글자로 적었는데 링크로 안 이은 글. 외딴 글을 잇는 자리다.
        n.write(Note(title="언급 받는 글", body="몸"))
        n.write(Note(title="말만 한 글", body="어제 언급 받는 글 을 다시 봤다"))
        n.write(Note(title="이은 글", body="[[언급 받는 글]] 이어 뒀다"))
        언 = dict(n.언급("언급 받는 글"))
        assert "말만 한 글" in 언, f"이름만 적은 글을 못 찾는다: {언}"
        assert "이은 글" not in 언, "이미 이은 글까지 언급으로 센다"
        assert "언급 받는 글" not in 언, "제 글을 언급으로 센다"
        assert "다시 봤다" in 언["말만 한 글"], "어느 줄인지 안 준다"

        # ★ 제목 조각에 `?`·`:` 를 쳐도 제안이 나와야 한다 — AI 가 틀린 제목을 고칠 길(did_you_mean)이다.
        assert "질문？ 답" in n.titles_like("질문?"), f"`?` 든 조각으로 제목을 못 찾는다: {n.titles_like('질문?')}"

        # ★★ **점 폴더는 글이 아니다** — 옵시디언 휴지통(`.trash`)의 지운 글이 검색에 되살아났다.
        for 점 in (".trash", ".obsidian", ".git"):
            (n.root / 점).mkdir(exist_ok=True)
            (n.root / 점 / f"점폴더 {점[1:]}.md").write_text("지운 글이다", encoding="utf-8")
        n.reindex()
        섞인 = [r[0] for r in n.conn.execute("SELECT title FROM notes WHERE title LIKE '점폴더 %'")]
        assert not 섞인, f"점 폴더 속 md 를 글로 센다: {섞인}"

        # ★★ **자기 자신을 가리키는 연결 폴더**가 있으면 훑기가 끝없이 따라 들어가다 멈추고
        #   뒤 글이 조용히 빠졌다. 정션을 만들 수 있는 자리에서만 잰다.
        import os as _os0                  # 이 함수 뒤쪽의 `import os` 보다 앞이라 딴 이름을 쓴다
        import subprocess as _sp

        (n.root / "고리 앞").mkdir(exist_ok=True)
        (n.root / "고리 앞" / "고리 뒤 글.md").write_text("고리 뒤에도 있다", encoding="utf-8")
        고리 = n.root / "고리 앞" / "되돌이"
        # ★ **맥·리눅스에는 `cmd` 가 없다.** 그냥 부르면 `FileNotFoundError: 'cmd'` 로
        #   검사가 통째로 터진다(맥에서 실제로 그랬다). 되돌이를 만드는 방법만 다르고
        #   재려는 것은 같다 — 윈도우는 정션, 그 밖은 심볼릭 링크.
        if _os0.name == "nt":
            _sp.run(["cmd", "/c", "mklink", "/J", str(고리), str(n.root)], capture_output=True)
        else:
            try:
                _os0.symlink(n.root, 고리, target_is_directory=True)
            except OSError:
                pass                  # 링크를 못 만드는 자리면 이 검사만 건너뛴다
        if 고리.exists():
            try:
                import time as _t2
                t0 = _t2.perf_counter()
                n.reindex()
                assert _t2.perf_counter() - t0 < 30, "연결 폴더를 따라 들어가 훑기가 늘어졌다"
                assert n.read("고리 뒤 글") is not None, "연결 폴더 때문에 글이 빠졌다"
                assert n.conn.execute(
                    "SELECT count(*) FROM notes WHERE title = '고리 뒤 글'").fetchone()[0] == 1,                     "연결 폴더를 따라가 같은 글을 여러 번 셌다"
            finally:
                # 고리만 지운다(가리키는 곳은 그대로). 정션은 `rmdir`, 심볼릭 링크는 `unlink`.
                고리.rmdir() if _os0.name == "nt" else 고리.unlink()

        # ★★ **260자 넘는 경로의 글도 세어야 한다.** 윈도우 긴 경로가 꺼진 PC 에서 조용히 빠졌다.
        import os as _os                    # 이 함수 뒤쪽에 `import os` 가 있어 `os` 가 지역 이름이다

        if _os.name == "nt":
            _B = chr(92)
            _앞 = _B + _B + "?" + _B
            _깊 = str(n.root)
            for _i in range(12):
                _깊 = _깊 + _B + ("긴폴더이름" * 4 + str(_i))
                try:
                    _os.mkdir(_앞 + _깊)
                except FileExistsError:
                    pass
            with open(_앞 + _깊 + _B + "아주 깊은 글.md", "w", encoding="utf-8") as _f:
                _f.write("아주 깊은 곳의 몸")
            try:
                n.reindex()
                assert n.read("아주 깊은 글") is not None, "260자 넘는 경로의 글이 색인에서 빠진다"
                assert "아주 깊은 글" in [r["title"] for r in n.search("깊은 곳의")], "긴 경로의 글이 안 찾힌다"
            finally:
                # 임시 폴더 정리(`rmtree`)도 260자를 못 넘는다 — 접두를 붙여 우리가 먼저 지운다.
                import shutil as _sh

                _sh.rmtree(_앞 + str(n.root) + _B + "긴폴더이름" * 4 + "0", ignore_errors=True)
                n.reindex()

        # ★★ **깨진 색인에서도 켜져야 한다.** 전원이 나가 색인이 깨지면 프로그램이 안 켜졌다.
        import tempfile as _tf2

        with _tf2.TemporaryDirectory() as _깨진곳:
            _뿌리 = Path(_깨진곳) / "notes"
            _색 = Path(_깨진곳) / "색인.db"
            _m = Notes(_뿌리, str(_색))
            _m.write(Note(title="살아남을 글", body="몸 글자"))
            _m.conn.close()
            _원 = _색.read_bytes()
            _색.write_bytes(b"garbage!" * 20 + _원[160:])
            for _곁 in ("-wal", "-shm"):
                Path(str(_색) + _곁).unlink(missing_ok=True)
            _m2 = Notes(_뿌리, str(_색))
            assert _m2.read("살아남을 글") is not None, "깨진 색인을 다시 만들지 못했다"
            assert list(Path(_깨진곳).glob("색인.db.깨짐-*")), "깨진 색인을 옆에 안 치웠다(지웠거나 덮었다)"
            _m2.conn.close()

        # ★ **알림은 기록 파일에도 남아야 한다** — 구운 판은 콘솔이 없어 print 가 사라진다.
        import os as _os5
        import tempfile as _tf4

        with _tf4.TemporaryDirectory() as _알곳:
            _옛자리 = _os5.environ.get("VC_DATA")
            _os5.environ["VC_DATA"] = _알곳
            try:
                _알림("시험 알림 한 줄")
                _로그 = Path(_알곳) / "vc-기록.log"
                assert _로그.exists() and "시험 알림 한 줄" in _로그.read_text(encoding="utf-8"),                     "알림이 기록 파일에 안 남는다(구운 판에서는 아무도 못 본다)"
            finally:
                if _옛자리 is None:
                    _os5.environ.pop("VC_DATA", None)
                else:
                    _os5.environ["VC_DATA"] = _옛자리

        # ★★ **같은 글에 동시에 덧붙여도 줄이 사라지면 안 된다** — 잠그기 전에는 80줄 중 40줄이 사라졌다.
        import threading as _th7

        n.write(Note(title="같이 쓰는 글", body="시작"))
        def _쌓기(표):
            for _i in range(30):
                n.append("같이 쓰는 글", f"{표}-{_i}")
        _실들 = [_th7.Thread(target=_쌓기, args=(x,)) for x in "AB"]
        [t.start() for t in _실들]; [t.join() for t in _실들]
        _몸 = n.read("같이 쓰는 글").body
        _남 = sum(1 for x in "AB" for _i in range(30) if f"{x}-{_i}" in _몸)
        assert _남 == 60, f"동시에 덧붙인 줄이 사라진다: 60줄 중 {_남}줄"

        # ★★ 이름 바꾸기가 링크를 고치는 동안 그 글에 덧붙인 줄도 안 사라진다.
        n.write(Note(title="바뀔 이름 가", body="대상"))
        n.write(Note(title="가리키는 글", body="[[바뀔 이름 가]]"))
        _멈춤 = []

        def _쌓기2():
            try:
                for _i in range(300):
                    n.append("가리키는 글", f"쌓은줄{_i}")
            finally:
                _멈춤.append(1)      # 실이 죽어도 아래 고리가 안 멈추면 검사가 끝없이 돈다
        _실 = _th7.Thread(target=_쌓기2); _실.start()
        _이름 = ["바뀔 이름 가", "바뀔 이름 나"]
        while not _멈춤:
            n.rename(_이름[0], _이름[1]); _이름.reverse()
        _실.join()
        _몸 = n.read("가리키는 글").body
        _남 = sum(1 for _i in range(300) if f"쌓은줄{_i}" + chr(10) in _몸 + chr(10))
        assert _남 == 300, f"이름 바꾸는 동안 덧붙인 줄이 사라진다: 300 중 {_남}"
        # 겹침은 우연이라 위 고리로는 잠금을 빼도 통과한다 — 잠금을 쥔 채 이름 바꾸기가 기다리는지 본다.
        import time as _t8

        with n._글잠금("가리키는 글"):
            _실 = _th7.Thread(target=n.rename, args=(_이름[0], _이름[1])); _실.start()
            _t8.sleep(0.5)
            assert f"[[{_이름[0]}]]" in read_text(n.path_of("가리키는 글")),                 "이름 바꾸기가 글 잠금을 안 기다리고 링크를 고친다(그 사이 덧붙인 줄이 사라진다)"
        _실.join()
        assert f"[[{_이름[1]}]]" in read_text(n.path_of("가리키는 글")), "잠금이 풀린 뒤 링크를 안 고쳤다"
        # ★ 글 잠금을 쥔 채 같은 실이 덧붙여도 안 멈춘다(고정·덮어쓰기가 읽고-쓰기를 감싼다).
        def _겹쳐잡기():
            with n._글잠금("가리키는 글"):
                n.append("가리키는 글", "겹쳐 잡은 줄")
        _실 = _th7.Thread(target=_겹쳐잡기, daemon=True); _실.start(); _실.join(5)
        assert not _실.is_alive(), "글 잠금을 쥔 채 덧붙이면 멈춘다(겹쳐 못 잡는다)"
        assert "겹쳐 잡은 줄" in n.read("가리키는 글").body
        # ★★ 한 글 색인은 연결 잠금을 **통째로** 쥔다 — 줄마다만 쥐면 그 사이에 딴 실이 끼어 IntegrityError.
        #   겹침은 우연이라 재현 대신, 안의 execute 가 불릴 때마다 이미 잠금을 쥐고 있었나를 본다.
        _쥠: list = []
        _길 = n.path_of("가리키는 글")        # 이 부름도 execute 라 재기 전에 구해 둔다
        _원 = n.conn.execute
        n.conn.execute = lambda *a: (_쥠.append(n.conn._잠금._is_owned()), _원(*a))[1]
        try:
            n._index_file(_길)
        finally:
            del n.conn.execute
        assert _쥠 and all(_쥠), f"한 글 색인이 연결 잠금을 통째로 안 쥔다: {_쥠}"
        # forget 도 「남았나 보고 지우기」라 통째로 쥔다 — 그 틈에 옮긴 글이 색인되면 그 링크가 지워진다.
        _쥠.clear()
        n.conn.execute = lambda *a: (_쥠.append(n.conn._잠금._is_owned()), _원(*a))[1]
        try:
            n.forget(str(n.root / "없는 자리" / "사라진 글.md"))
        finally:
            del n.conn.execute
        assert _쥠 and all(_쥠), f"forget 이 연결 잠금을 통째로 안 쥔다: {_쥠}"
        # ★★ 이름 바꾸기는 새 이름을 잠근다 — 「없다」고 본 뒤 그 이름이 생기면 덮지 말고 물러나야 한다.
        n.write(Note(title="옮길 글", body="옮길 몸"))
        _결과: list = []
        with n._글잠금("겹칠 새 이름"):
            _실 = _th7.Thread(target=lambda: _결과.append(n.rename("옮길 글", "겹칠 새 이름")), daemon=True)
            _실.start()
            _t8.sleep(0.4)
            assert _실.is_alive(), "이름 바꾸기가 새 이름 잠금을 안 기다린다"
            n.write(Note(title="겹칠 새 이름", body="먼저 생긴 몸"))
        _실.join(10)
        assert _결과 == [False], f"그 사이 생긴 새 이름으로 바꿨다: {_결과}"
        assert n.read("겹칠 새 이름").body.strip() == "먼저 생긴 몸", "먼저 생긴 글을 덮었다"
        assert n.read("옮길 글") is not None, "물러났는데 옛 글이 사라졌다"

        # ★★ `/정규식/` 검색 — 낱말 색인이 못 찾는 꼴(ERR-1234)을 찾는다. 틀린 정규식은 0장.
        n.write(Note(title="오류 기록 가", body="로그에 ERR-1234 가 떴다"))
        n.write(Note(title="오류 기록 나", body="로그에 ERR-12 만 떴다"))
        _찾 = [r["title"] for r in n.search(r"/ERR-\d{4}/", k=10)]
        assert _찾 == ["오류 기록 가"], f"정규식 검색이 틀린 것을 준다: {_찾}"
        assert [r["title"] for r in n.search(r"로그 /ERR-\d{4}/", k=10)] == ["오류 기록 가"], "낱말과 같이 쓴 정규식이 안 걸린다"
        assert n.search("/[/", k=10) == [], "틀린 정규식인데 뭔가 준다"
        assert n.search(r"/err-\d{4}/", k=10) and n.search(r"/ERR-\d{4}/ -없는말", k=10) is not None
        assert not n._정규식꼴.search("path:2026/09 회의"), "path:2026/09 를 정규식으로 뽑는다"
        assert [m.group(1) for m in n._정규식꼴.finditer(r"a /x\/y/ b")] == [r"x\/y"], "빗금을 품은 정규식을 못 뽑는다"

        # 지우기도 「남기고 → 지우기」라 글 잠금을 기다려야 한다.
        n.write(Note(title="지울 글", body="몸"))
        with n._글잠금("지울 글"):
            _실 = _th7.Thread(target=n.delete, args=("지울 글",), daemon=True); _실.start()
            _t8.sleep(0.4)
            assert _실.is_alive(), "delete 가 글 잠금을 안 기다린다"
            n.append("지울 글", "지우기 직전에 붙인 줄")
        _실.join(10)
        assert n.read("지울 글") is None
        assert any("지우기 직전에 붙인 줄" in read_text(p) for _, p in n.history("지울 글")), \
            "지우기 직전에 붙인 줄이 이력에도 없다"

        # ★★ 지난 판을 못 남기면 지우기·되돌리기는 멈추고 알린다 — 그냥 하면 되돌릴 판 없이 글이 사라진다.
        n.write(Note(title="판 못 남길 글", body="살아야 할 몸"))
        n.keep_history(n.path_of("판 못 남길 글"), "옛 몸", always=True)
        _판자리 = n.history("판 못 남길 글")[0][1]
        _옛남기기 = n.keep_history

        def _못남김(*a, **k):
            raise PermissionError("이력 폴더가 잠겼다")
        n.keep_history = _못남김
        try:
            for _일 in (lambda: n.delete("판 못 남길 글"), lambda: n.restore("판 못 남길 글", _판자리)):
                try:
                    _일()
                except WriteBlocked:
                    pass
                else:
                    raise AssertionError("지난 판을 못 남겼는데 지우기·되돌리기를 그냥 했다")
        finally:
            n.keep_history = _옛남기기
        assert n.read("판 못 남길 글") is not None and "살아야 할 몸" in n.read("판 못 남길 글").body, \
            "판을 못 남겼는데 글이 사라지거나 덮였다"

        # ★★ 덮어쓰기도 같다 — 지금 글을 못 읽거나(잠김) 판을 못 남기면 덮지 않는다.
        _덮을길 = n.path_of("판 못 남길 글")
        _원글 = read_text(_덮을길)
        _옛읽기 = globals()["read_text"]

        def _잠긴읽기(p, _옛=_옛읽기):
            if Path(p) == _덮을길:
                raise PermissionError("딴 프로그램이 잡고 있다")
            return _옛(p)
        for _막기 in ("읽기", "남기기"):
            if _막기 == "읽기":
                globals()["read_text"] = _잠긴읽기
            else:
                n.keep_history = _못남김
            try:
                n.write(Note(title="판 못 남길 글", body=f"덮으려는 몸 {_막기}"))
            except WriteBlocked:
                pass
            else:
                raise AssertionError(f"{_막기}가 막혔는데 그냥 덮었다")
            finally:
                globals()["read_text"] = _옛읽기
                n.keep_history = _옛남기기
            assert read_text(_덮을길) == _원글, f"{_막기}가 막혔는데 글이 바뀌었다"

        # 오늘 일지 만들기·지난 판 되돌리기도 읽고-쓰기라 글 잠금을 기다려야 한다.
        n.keep_history(n.path_of("가리키는 글"), read_text(n.path_of("가리키는 글")), always=True)
        _판 = n.history("가리키는 글")[0][1]
        for _일, _인자 in ((n.daily, ("2031-01-02",)), (n.restore, ("가리키는 글", _판))):
            _잠글 = _인자[0]
            with n._글잠금(_잠글):
                _실 = _th7.Thread(target=_일, args=_인자, daemon=True); _실.start()
                _t8.sleep(0.4)
                assert _실.is_alive(), f"{_일.__name__} 가 글 잠금을 안 기다린다"
            _실.join(10)
            assert not _실.is_alive()

        # ★ **외딴 글**(옵시디언의 「고아 노트」). AI 가 3천 장을 붓는 창고라 쌓이기 쉽고,
        #   그물에서 빠진 글은 뜻 검색 말고는 닿을 길이 없다. 고정한 것은 뺀다.
        n.write(Note(title="외톨이", body="아무것도 안 가리킨다"))
        외딴 = n.외딴것()
        assert "외톨이" in 외딴, f"외딴 글을 못 찾는다: {외딴}"
        assert "고정된 것" not in 외딴, "고정한 것까지 외딴 것으로 센다"
        assert "아침" not in 외딴, "이어진 글을 외딴 것으로 센다"

        assert n.외딴것수() >= len(외딴), "모두 몇 장인지를 목록보다 적게 센다"
        sub = n.subgraph(["요약", "보고서"])
        assert set(sub) == {"요약", "보고서"}
        assert all(all(x in sub for x in v) for v in sub.values()), "밖으로 나가는 선이 남았다"

        # 시간 축 — 20년치에서 "작년 그거"를 찾는 길.
        n.write(Note(title="작년 일", body="", created="2025-03-02T10:00:00Z"))
        n.write(Note(title="재작년 일", body="", created="2024-11-09T10:00:00Z"))
        years = dict(n.by_year())
        assert years.get("2025") == 1 and years.get("2024") == 1, n.by_year()
        assert n.by_year()[0][0] >= n.by_year()[-1][0], "최근이 앞에 안 온다"
        assert [t for t, _ in n.in_year("2025")] == ["작년 일"]
        assert n.in_year("1999") == []

        # 태그. 하위 태그는 상위로도 걸린다.
        assert n.by_tag("장소") == ["회사"]
        assert n.by_tag("할일") == ["아침", "회사"], n.by_tag("할일")
        assert n.by_tag("할일/출근") == ["아침", "회사"]
        assert dict(n.all_tags())["할일/출근"] == 2

        # 별칭은 온 저장소에서 하나뿐이다. 먼저 쓴 쪽이 이긴다.
        n.write(Note(title="딴것", body="", aliases=["직장"]))
        assert n.resolve("직장") == "회사", "남의 별칭을 빼앗았다"

        # 파일에 적히고 다시 읽힌다 — 옵시디언에서 열어 고칠 수 있어야 한다.
        raw = n.path_of("회사").read_text(encoding="utf-8")
        assert "aliases" in raw, raw
        assert n.read("회사").aliases == ["직장", "사무실"]

        # 덧붙이기가 기본이다. 덮어쓰기가 기본이면 어제 적은 것이 오늘 것에 지워진다.
        n.append("일지", "오전: 견적 보냄")
        n.append("일지", "오후: 회신 받음")
        assert "오전" in n.read("일지").body and "오후" in n.read("일지").body

        # 다시 써도 신원은 그대로다. 20년 뒤 "언제 처음 적었나"에 답해야 한다.
        first = n.read("일지")
        n.write(Note(title="일지", body="통째로 새로 씀"))
        assert n.read("일지").created == first.created and n.read("일지").id == first.id

        # 사람이 손댄 표시는 파일에 남는다 — 이걸로 AI 덮어쓰기를 막는다.
        marked = n.read("일지"); marked.edited_by = "사람"; n.write(marked)
        assert n.read("일지").edited_by == "사람"
        assert "edited_by" in n.path_of("일지").read_text(encoding="utf-8")

        # 긴 글을 쓰는 중에 읽어도 반쪽이 안 보인다 — 옆에 쓰고 자리를 바꾼다.
        import threading
        long_text = "가" * 120_000
        hurt = []

        def keep_reading():
            f = n.path_of("긴글")
            for _ in range(400):
                try:
                    got = f.read_text(encoding="utf-8").split("---", 2)[-1].strip()
                except (OSError, UnicodeDecodeError):
                    hurt.append("깨짐"); return
                if got and len(set(got)) > 1:
                    hurt.append("섞임"); return

        n.write(Note(title="긴글", body=long_text))
        t = threading.Thread(target=keep_reading); t.start()
        for _ in range(6):
            n.write(Note(title="긴글", body="나" * 120_000))
            n.write(Note(title="긴글", body=long_text))
        t.join()
        assert not hurt, hurt
        assert not list(n.root.rglob("*.tmp")), "임시 파일이 남았다"

        # 색상 코드는 태그가 아니다. 실제 기록에서 `#0E1116`이 태그로 잡혔다.
        n.write(Note(title="색 메모", body="배경 #0E1116 글자 #3D6BFF 이고 #디자인 태그"))
        assert n.read("색 메모").tags() == ["디자인"], n.read("색 메모").tags()

        # 경로로 건 링크도 닿는다 — 옵시디언은 [[폴더/노트]]를 받는다.
        n.write(Note(title="쿼리", body=""))
        n.write(Note(title="안내", body="[[prompts/쿼리]] 참고"))
        assert n.resolve("prompts/쿼리") == "쿼리"
        assert "쿼리" in n.neighbors("안내"), "경로형 링크가 안 이어진다"
        assert "prompts/쿼리" not in dict(n.unresolved())

        # --- 첨부 ---
        #
        # 첨부는 항목이 아니다. 링크로 세면 "아직 없는 것"에 사진 이름이 쌓이고
        # 그래프에 유령 점이 생긴다.
        png = bytes.fromhex("89504e470d0a1a0a") + b"fake"
        name = n.save_attachment(png, ".png", "회의 사진")
        assert name.endswith(".png") and n.attachment_path(name).exists()
        assert n.attachment_path(name).read_bytes() == png

        # 같은 이름이 또 오면 덮지 않고 번호를 붙인다 — 남이 가리키던 그림이 바뀌면 안 된다.
        again = n.save_attachment(b"another", ".png", "회의 사진")
        assert again != name, (name, again)

        n.write(Note(title="사진 낀 글", body=f"현장: ![[{name}]] 참고 [[회사]]"))
        got = n.read("사진 낀 글")
        assert got.attachments() == [name], got.attachments()
        assert got.links() == [("회사", "")], got.links()      # 첨부는 링크가 아니다
        assert got.embeds() == [], "첨부가 항목 끼움으로 샜다"
        assert name not in dict(n.unresolved()), "첨부가 미해결 링크로 샜다"
        # --- 작은 사진(썸네일) — 목록 카드가 원본을 통째로 받지 않게 ---
        import io as _io

        from PIL import Image as _Image

        큰것 = _io.BytesIO()
        _Image.new("RGB", (1600, 1200), (200, 60, 40)).save(큰것, "JPEG", quality=95)
        사진 = n.save_attachment(큰것.getvalue(), ".jpg", "큰 사진")
        작은 = n.thumbnail_path(사진, 320)
        assert 작은 is not None and 작은.is_file(), "작은 사진을 못 만든다"
        with _Image.open(작은) as _t:
            assert _t.width == 320, _t.size
        원본크기 = n.attachment_path(사진).stat().st_size
        assert 작은.stat().st_size * 4 < 원본크기, (작은.stat().st_size, 원본크기)
        # 두 번째는 다시 안 만든다 — 같은 파일을 그대로 준다
        먼저 = 작은.stat().st_mtime_ns
        assert n.thumbnail_path(사진, 320).stat().st_mtime_ns == 먼저, "썸네일을 매번 다시 만든다"
        # 아무 너비나 받지 않는다(폴더가 무한히 는다) · 못 읽는 꼴이면 None(원본으로 간다)
        assert n.thumbnail_path(사진, 321) is None
        assert n.thumbnail_path(name, 320) is None, "깨진 png 로 썸네일을 만들었다고 한다"
        assert n.thumbnail_path("없는사진.png", 320) is None

        assert n.attachment_path("없는사진.png") is None
        assert not is_attachment("그냥 항목")
        # 표 안 링크 `[[제목\|보일 말]]` — 제목 끝에 `\` 가 붙으면 끊긴 링크다
        assert parse_links("| [[제품 · a-1\\|a-1]] | [[회의#8월\\|보기]] |") == [("제품 · a-1", ""), ("회의", "8월")]
        # 고정 · 보관 · 색 · 휴지통(편의 기능 18·27·28·30번)
        n.write(Note(title="표시 시험", body="몸"))
        g = n.mark("표시 시험", pinned=True, archived=True, color="노랑")
        assert g.pinned and n.read("표시 시험").extra.get("보관") is True and n.read("표시 시험").extra.get("색") == "노랑"
        n.mark("표시 시험", archived=False, color="")
        assert "보관" not in n.read("표시 시험").extra and "색" not in n.read("표시 시험").extra and n.read("표시 시험").pinned
        try:
            n.mark("표시 시험", color="검정")
            raise AssertionError("모르는 색을 받았다")
        except ValueError:
            pass
        assert n.mark("없는 글", pinned=True) is None
        n.delete("표시 시험")
        휴 = [x for x in n.trashed() if x[0] == "표시 시험"]
        assert 휴, "지운 글이 휴지통에 없다"
        assert n.untrash(휴[0][2]) == "표시 시험" and n.read("표시 시험").body.strip() == "몸", "못 되살렸다"
        assert not [x for x in n.trashed() if x[0] == "표시 시험"], "되살렸는데 휴지통에 남았다"
        assert n.untrash(n.root / "표시 시험.md") is None, "이력 밖 파일을 되살리기로 받았다"
        # 사진 글자 주석은 미리보기에 안 나오고, 찾기에는 걸린다
        assert 카드미리보기("정수기 받음\n\n%%\n사진 글자 (a.jpg):\n송장 7788\n%%") == "정수기 받음"

        # --- 폴더 ---
        #
        # 새로 만드는 것은 연/월 폴더로 간다. 20년치를 한 폴더에 쌓으면 탐색기도
        # 옵시디언도 버거워진다.
        made = n.write(Note(title="폴더 시험", body="", created="2019-04-07T09:00:00Z"))
        assert made.parent.name == "04" and made.parent.parent.name == "2019", made

        # **사람이 옮겨 둔 자리는 지킨다.** 저장할 때마다 되돌리면 정리가 흐트러진다.
        moved = n.root / "내가 정리한 곳"
        moved.mkdir()
        newp = moved / made.name
        made.replace(newp)
        n.reindex()
        again = n.read("폴더 시험")
        assert again is not None, "옮겼더니 못 읽는다"
        again.body = "고침"
        assert n.write(again) == newp, "옮겨 둔 자리를 안 지킨다"

        # 하위 폴더에 있어도 링크·태그가 그대로 걸린다.
        (moved / "깊은 것.md").write_text("[[회사]] 참고 #깊음", encoding="utf-8")
        n.reindex()
        assert n.resolve("깊은 것") == "깊은 것"
        assert "깊은 것" in n.neighbors("회사"), "하위 폴더의 링크를 놓친다"
        assert n.by_tag("깊음") == ["깊은 것"]

        # 같은 이름이 두 폴더에 있으면 드러낸다. 이름이 곧 링크의 열쇠라 하나여야 한다.
        (moved / "회사.md").write_text("사본", encoding="utf-8")
        n.reindex()
        assert ("회사", 2) in n.duplicates(), n.duplicates()
        (moved / "회사.md").unlink()
        n.reindex()
        assert n.duplicates() == []

        # 색인은 지우고 다시 만들 수 있다 — 태그·별칭까지 같이 돌아온다.
        for t in ("notes", "links", "tags", "aliases"):
            n.conn.execute(f"DELETE FROM {t}")
        n.conn.commit()
        n.reindex()
        assert n.resolve("사무실") == "회사" and n.by_tag("장소") == ["회사"]


    # --- 검색 문법 ---
    with tempfile.TemporaryDirectory() as tmp:
        n = Notes(Path(tmp) / "notes")
        n.write(Note(title="배포 준비", body="릴리스 절차. #할일/배포", kind="note"))
        n.write(Note(title="배포 실패", body="롤백했다. #할일/배포", kind="note"))
        n.write(Note(title="검색 모듈", body="정확한 구절 그대로 들어 있다", kind="skill"))
        n.reindex()
        got = lambda q: {r["title"] for r in n.search(q, k=9)}
        assert got("배포") == {"배포 준비", "배포 실패"}, got("배포")
        assert got("배포 -실패") == {"배포 준비"}, got("배포 -실패")
        assert got("tag:할일") == {"배포 준비", "배포 실패"}, got("tag:할일")
        assert got("태그:할일/배포") == {"배포 준비", "배포 실패"}
        assert got("kind:skill") == {"검색 모듈"}, got("kind:skill")
        assert got("종류:skill") == {"검색 모듈"}
        assert got('"정확한 구절"') == {"검색 모듈"}, got('"정확한 구절"')
        assert got('"구절 정확한"') == set(), "구절은 순서가 맞아야 한다"
        assert got("tag:없는것ZZZ") == set(), "좁혔는데 없으면 0건이 옳은 답이다"

        # ★★ **`_` 와 `%` 가 와일드카드로 새면 안 된다**(2026-09-20 · 폴더 칸을 만들다 잡았다).
        #   SQL `LIKE` 에서 `_` 는 「아무 글자 하나」다. 그대로 넣었더니 `path:_정리` 가
        #   「`_정리` 폴더의 1장」 대신 **「제목에 '정리'가 든 3장」까지 4장**을 내놓았다.
        #   창고에는 `_서식`·`_정리` 처럼 밑줄로 시작하는 폴더가 있다.
        밑줄방 = n.root / "_정리"
        밑줄방.mkdir(exist_ok=True)
        n.write(Note(title="정리함 글", body="여기 있다"), at=밑줄방 / "정리함 글.md")
        n.write(Note(title="딴 곳의 정리 글", body="제목에 정리가 들었을 뿐"))
        n.write(Note(title="퍼센트 글", body="몸", extra={"status": "100%끝"}))
        # ★ `%` 를 안 막으면 「100 + 아무거나 + 끝」 이 되어 **이것까지 걸린다**
        n.write(Note(title="퍼센트 아닌 글", body="몸", extra={"status": "100아무거나끝"}))
        n.reindex()
        assert got("path:_정리") == {"정리함 글"}, got("path:_정리")
        assert got("status:100%끝") == {"퍼센트 글"}, got("status:100%끝")
        assert 라이크("a_b%c") == r"a\_b\%c", 라이크("a_b%c")

        # ★ **폴더 나무는 위 폴더도 센다** — 「2019」 를 눌러 그해 전부를 볼 수 있어야 한다.
        n.write(Note(title="나무 시험 글", body="몸", created="2019-04-07T09:00:00Z"))
        n.reindex()
        나무 = n.폴더나무()
        # 층(`wiki/`) 아래에 연/월이 선다 — 그래서 한 단계 깊다(오너 결정 2026-09-20)
        assert ("wiki", 0, 1) in [(t, d, c) for t, d, c in 나무 if t == "wiki"] or \
               any(t == "wiki" and d == 0 for t, d, c in 나무), 나무
        assert ("2019", 1, 1) in 나무, 나무
        assert ("04", 2, 1) in 나무, 나무
        assert [x for x in 나무 if x[0] == "_정리"], 나무

        # ★★ **앞머리 값으로도 찾는다**(오너 2026-09-20). 옵시디언 볼트를 들이니
        #   `status` 가 101장, `source` 가 97장이었는데 **그 값으로 찾을 길이 없었다** —
        #   `status:active` 가 83장을 두고 **2장**을 내놓았다(모르는 이름은 낱말로 쳤다).
        #   0장이 아니라 2장이라, 사람은 그게 전부인 줄 안다. 그런 답이 제일 나쁘다.
        n.write(Note(title="앞머리 가", body="몸", extra={"status": "active", "source": "오너 지시"}))
        n.write(Note(title="앞머리 나", body="몸", extra={"status": "draft"}))
        n.write(Note(title="앞머리 다", body="몸",
                     extra={"status": "resolved  # 원인 확정", "tags": ["급함", "배포"]}))
        n.reindex()
        assert got("status:active") == {"앞머리 가"}, got("status:active")
        assert got("status:draft") == {"앞머리 나"}, got("status:draft")
        # 값은 앞자리로 본다 — 뒤에 주석이 붙어도 걸린다
        assert got("status:resolved") == {"앞머리 다"}, got("status:resolved")
        assert got("source:오너") == {"앞머리 가"}, got("source:오너")
        # 목록 값도 펴서 담는다
        assert "앞머리 다" in got("tags:급함"), got("tags:급함")
        # 빼기도 된다
        assert "앞머리 가" not in got("-status:active status:draft OR status:active"), "빼기가 안 먹는다"
        # ★ **창고에 없는 이름은 지금까지처럼 낱말로 친다.** 글 속의 `09:30` 이나
        #   `C:` 를 찾을 때 0장이 되면 안 된다 — 되던 것이 조용히 막히는 쪽이 더 나쁘다.
        n.write(Note(title="시각 메모", body="회의는 09:30 에 시작한다"))
        n.reindex()
        assert got("09:30") == {"시각 메모"}, got("09:30")
        assert "status" in n.앞머리이름들() and "09" not in n.앞머리이름들(), sorted(n.앞머리이름들())

        # ★★ **쓰던 색인에도 채워져야 한다.** `CREATE TABLE IF NOT EXISTS` 는 표만
        #   만들고 내용을 안 채운다 — 표만 생기고 비면 `status:` 가 **0장**이 되는데
        #   「되기는 되는데 아무것도 안 나온다」가 제일 나쁜 꼴이다.
        n.conn.execute("DELETE FROM props")
        n.conn.commit()
        n._앞머리이름 = None
        n._앞머리채울까 = True       # 색인을 열 때 이 상태가 된다
        n.reindex()
        assert got("status:active") == {"앞머리 가"}, "쓰던 색인에 앞머리가 안 채워진다"
        assert not n._앞머리채울까, "한 번 채우고 나서도 매번 전부 다시 읽는다"
        assert got("path:notes") >= {"배포 준비"}, got("path:notes")
        # ★★ **사람은 `/` 로 적는데 윈도우 경로는 `\` 다.** `path:2026/09` 가 영영
        #   안 걸렸다 — 0장이 나오는데 왜인지도 안 보였다. 적는 대로 걸려야 한다.
        깊 = n.path_of("배포 준비").parent.name
        assert got(f"path:{깊}") >= {"배포 준비"}, f"한 칸짜리 경로가 안 걸린다: {깊}"
        두칸 = "/".join(n.path_of("배포 준비").parts[-3:-1])
        assert got(f"path:{두칸}") >= {"배포 준비"}, f"슬래시로 적은 경로가 안 걸린다: {두칸}"
        assert got("year:" + _now()[:4]) >= {"배포 준비"}
        # 모르는 이름은 **그냥 낱말 둘**로 친다. 값만 남기고 이름을 버리면
        # `결정:22` 같은 진짜 글자가 조용히 사라진다.
        assert got("xyz:배포") == set(), got("xyz:배포")
        n.write(Note(title="결정 기록", body="결정 22번을 따른다"))
        n.reindex()
        assert got("결정:22") == {"결정 기록"}, got("결정:22")

        # --- 낱말 색인이 비어도 스스로 채운다 ---
        # 프로그램을 새 판으로 올리면 표만 생기고 파일은 안 바뀐다. 그때 검색이
        # 조용히 죽으면 안 된다(실제로 109개 중 9개만 들어 있었다).
        # 색인이 파일이어야 다시 열었을 때가 재현된다(기본값은 메모리라 매번 새것이다).
        db = str(Path(tmp) / "idx.db")
        one = Notes(Path(tmp) / "notes", db)
        many = one.conn.execute("SELECT count(*) FROM notes").fetchone()[0]
        assert many > 0
        one.conn.execute("DELETE FROM search")
        one.conn.commit()
        one.conn.close()
        again = Notes(Path(tmp) / "notes", db, index_now=False)
        assert again.conn.execute("SELECT count(*) FROM search").fetchone()[0] == many
        assert {r["title"] for r in again.search("배포")} == {"배포 준비", "배포 실패"}
        again.conn.close()

    # 할 일 뒤집기 — 원문을 고쳐야 한다. 목록 아닌 곳의 `[x]`는 안 건드린다.
    todo = "- [ ] 하나" + chr(10) + "- [x] 둘" + chr(10) + "  * [ ] 셋" + chr(10) + "글 [x] 은 그대로"
    assert flip_task(todo, 0)[0].splitlines()[0] == "- [x] 하나"
    assert flip_task(todo, 0)[1] is True
    assert flip_task(todo, 1)[0].splitlines()[1] == "- [ ] 둘"
    assert flip_task(todo, 2)[0].splitlines()[2] == "  * [x] 셋"
    assert flip_task(todo, 3) is None, "없는 번호는 아무 일도 안 한다"
    assert "글 [x] 은 그대로" in flip_task(todo, 0)[0]

    # 소제목 — 코드 덩어리 안의 #은 소제목이 아니다
    doc = (chr(10)).join(["# 하나", "글", "## 둘", "```python", "# 주석이다", "```", "### 셋"])
    assert headings(doc) == [(1, "하나"), (2, "둘"), (3, "셋")], headings(doc)

    # --- 지난 판 ---
    with tempfile.TemporaryDirectory() as tmp:
        # 자체점검은 `__main__`으로 도는지라 `import notes`는 **딴 사본**이 된다.
        # 전역을 직접 만져야 이 파일의 함수가 본다.
        gap = globals()["HISTORY_GAP_SEC"]
        globals()["HISTORY_GAP_SEC"] = 0     # 시험에서는 간격을 두지 않는다
        try:
            n = Notes(Path(tmp) / "notes")
            n.write(Note(title="계획", body="처음"))
            for b in ("둘째", "셋째", "셋째", "넷째"):
                n.write(Note(title="계획", body=b))
            past = n.history("계획")
            assert len(past) == 3, [w for w, _ in past]   # 같은 내용은 안 남는다
            assert n.read("계획").body.strip() == "넷째"
            assert n.restore("계획", past[-1][1])
            assert n.read("계획").body.strip() == "처음"
            # 되돌린 것이 잘못이었을 때 돌아올 길
            assert any("넷째" in f.read_text(encoding="utf-8") for _, f in n.history("계획"))

            # **이름을 바꿔도 지난 판이 따라와야 한다.** 이력 폴더가 이름으로
            # 잡히므로 안 옮기면 옛 이름에 남아, 이름 바꾼 항목은 영영 못 되돌린다.
            n.write(Note(title="옛이름", body="처음"))
            n.write(Note(title="옛이름", body="둘째"))
            assert n.history("옛이름"), "이력이 안 생겼다"
            assert n.rename("옛이름", "새이름")
            assert n.history("새이름"), "이름 바꾸니 지난 판이 사라졌다"
            assert not n.history("옛이름"), "옛 이름 쪽에 남아 있다"
            assert n.restore("새이름", n.history("새이름")[0][1])
            n.delete("새이름")          # 뒤 검사가 항목 하나만 세고 있다

            # **5분 묶음이 살아 있어도 되돌리기 직전 글은 남아야 한다.**
            # 위 검사는 간격을 0으로 두고 하는 바람에 이 자리를 못 잡았다 —
            # 낯선 PC 에서 되돌리기 직전 4줄이 파일에도 이력에도 없었다.
            globals()["HISTORY_GAP_SEC"] = gap
            n.write(Note(title="계획", body="되돌리기 직전 글"))
            back = n.history("계획")[-1][1]
            assert n.restore("계획", back)
            assert any("되돌리기 직전 글" in f.read_text(encoding="utf-8")
                       for _, f in n.history("계획")), "되돌리기 직전 글이 사라졌다"
            globals()["HISTORY_GAP_SEC"] = 0
            # 지난 판은 항목이 아니다
            n.reindex()
            assert n.conn.execute("SELECT count(*) FROM notes").fetchone()[0] == 1
            assert n.search("넷째") == [] or all(
                r["title"] == "계획" for r in n.search("넷째"))
            # 판 수를 넘기면 옛것부터 버린다
            for i in range(HISTORY_KEEP + 5):
                n.write(Note(title="계획", body=f"판 {i}"))
            assert len(n.history("계획")) <= HISTORY_KEEP, len(n.history("계획"))
        finally:
            globals()["HISTORY_GAP_SEC"] = gap

    # --- 같은 제목이 두 폴더에 ---
    # 20년이면 반드시 생긴다. 제목으로 자리를 다시 찾으면 **엉뚱한 파일에 쓴다.**
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "notes"
        (root / "2026" / "01").mkdir(parents=True)
        (root / "2027" / "03").mkdir(parents=True)
        (root / "2026" / "01" / "회의.md").write_text("예산 얘기", encoding="utf-8")
        (root / "2027" / "03" / "회의.md").write_text("인사 얘기", encoding="utf-8")
        n = Notes(root)
        pair = n.twins("회의")
        assert len(pair) == 2, pair
        assert n.twins("없는것") == []
        assert n.read_at(pair[0]).body.strip() == "예산 얘기"
        assert n.read_at(pair[1]).body.strip() == "인사 얘기"
        # 2027 것을 고쳐도 2026 것은 그대로여야 한다
        keep = (root / "2026" / "01" / "회의.md").read_text(encoding="utf-8")
        later = n.read_at(pair[1])
        later.body = "인사 얘기. 덧붙임."
        n.write(later, pair[1])
        assert "덧붙임" in (root / "2027" / "03" / "회의.md").read_text(encoding="utf-8")
        assert (root / "2026" / "01" / "회의.md").read_text(encoding="utf-8") == keep

    # --- 오늘 일지 · 서식 ---
    with tempfile.TemporaryDirectory() as tmp:
        n = Notes(Path(tmp) / "notes")
        forms = n.template_root()
        forms.mkdir(parents=True, exist_ok=True)   # 규칙 파일 때문에 이미 있다
        (forms / "일지.md").write_text("# {{날짜}}" + chr(10) * 2 + "- [ ] ", encoding="utf-8")
        (forms / "회의록.md").write_text("# {{제목}} / {{시각}} / {{모르는것}}", encoding="utf-8")
        # 규칙 파일도 그 폴더에 있다. 서식 목록에서 빼고 본다.
        assert [t for t in n.templates() if t != Path(n.RULE_FILE).stem]             == ["일지", "제품", "회의록"], n.templates()
        today = time.strftime("%Y-%m-%d")
        first = n.daily()
        assert first.title == today
        assert today in first.body, first.body
        # 두 번 불러도 새로 안 만든다 — 하루에 여러 번 눌러도 어제 적은 게 안 날아간다
        first.body += chr(10) + "손으로 적음"
        n.write(first)
        assert "손으로 적음" in n.daily().body
        # 모르는 자리는 그대로 둔다. 지우면 오타가 흔적도 없이 사라진다.
        got = n.fill_slots(n.template("회의록"), "주간 회의")
        assert got.startswith("# 주간 회의 / ")
        assert "{{모르는것}}" in got, got
        # 서식은 항목이 아니다
        n.reindex()
        assert n.read("일지") is None
        assert n.conn.execute("SELECT count(*) FROM notes").fetchone()[0] == 1
        # VC 가 적는 기계 기록 요약(`_VC기록/`, 결정 17)도 항목이 아니다 — 기록 폴더는 메모만.
        (n.root / VC_LOG_DIR).mkdir(exist_ok=True)
        (n.root / VC_LOG_DIR / "상태.md").write_text("# VC 상태\n\n- 서버 열었다\n", encoding="utf-8")
        n.reindex()
        assert n.conn.execute("SELECT count(*) FROM notes").fetchone()[0] == 1, "기계 기록 요약을 항목으로 센다"
        # 5단계 — 규칙 파일은 서식 목록에 안 뜨고, 기본 「제품」 서식은 처음 한 번만 생긴다.
        assert Notes.RULE_FILE[:-3] not in n.templates(), n.templates()
        with tempfile.TemporaryDirectory() as 새:
            처음 = Notes(Path(새) / "창고")
            assert "제품" in 처음.templates(), 처음.templates()
            assert "{{날짜}}" in 처음.template("제품") and "받은날" in 처음.template("제품"), 처음.template("제품")
            (처음.template_root() / "제품.md").unlink()   # 사람이 지웠다
            처음.write_rules()
            assert "제품" not in 처음.templates(), "지운 기본 서식이 다시 생긴다"
            # ★ 전부터 쓰던 창고(규칙 파일은 있고 표시가 없음)에도 한 번은 들어간다
            옛창고 = Path(새) / "옛창고"
            (옛창고 / TEMPLATE_DIR).mkdir(parents=True)
            (옛창고 / TEMPLATE_DIR / Notes.RULE_FILE).write_text("# 옛 규칙\n", encoding="utf-8")
            옛 = Notes(옛창고)
            assert "제품" in 옛.templates(), "이미 쓰던 창고에는 기본 서식이 영영 안 생긴다"
            assert read_text(옛창고 / TEMPLATE_DIR / Notes.RULE_FILE) == "# 옛 규칙\n", "사람이 고친 규칙을 덮었다"

    # --- 뜻으로 찾기 ---
    # **모델 없이 검사한다.** 자체점검이 모델 파일에 매이면, 모델이 없는 PC에서는
    # 검사 자체를 못 돌린다.
    # 소제목 **뒤에서 시작하는** 조각이 생길 만큼 길어야 이름표를 확인할 수 있다.
    # 뜻을 재는 글은 **제목 + 앞부분**이다. 더 넣으면 오히려 못 맞힌다(위 표).
    card = meaning_card("회의록", "가" * 5000)
    assert card.startswith("회의록" + chr(10))
    assert len(card) == len("회의록") + 1 + CARD_CHARS, len(card)
    # ★★ **한국어는 조사가 붙어서 글자 그대로는 거의 안 맞는다.** 물음은 「예산을」인데
    #   본문은 「예산은」이라 `in` 이 거짓이다 — 끝 한 글자를 뗀 것도 같이 본다.
    assert "예산" in 물음낱말("이번 회의에서 예산을 얼마로 정했나"), 물음낱말("예산을")
    assert 요약("첫 줄은 인사다." + chr(10) * 2 + "예산은 삼천만 원으로 정했다.",
              물음="이번 회의에서 예산을 얼마로 정했나").startswith("예산은"),         "요약이 물음에 걸린 줄을 못 고른다 — 조사 때문에 어긋난다"
    # ★ **자른 요약은 자른 티가 나야 한다.** 그 표시가 없으면 읽는 쪽이 「이게 끝인가」를
    #   확인하려고 2단을 부른다 — 점 하나 아끼고 900자를 태우는 셈이다.
    긴줄 = "가" * 300
    잰것 = 요약(긴줄)
    assert 잰것.endswith("…") and len(잰것) == 121, f"자르고도 말을 안 한다: {len(잰것)}"
    assert not 요약("짧은 한 줄이다.").endswith("…"), "안 잘랐는데 잘랐다고 한다"
    assert meaning_card("이름만", "") == "이름만"
    assert meaning_card("빈몸", "   ") == "빈몸"

    with tempfile.TemporaryDirectory() as tmp:
        n = Notes(Path(tmp) / "notes")
        n.write(Note(title="과일", body="사과를 먹었다. 사과는 빨갛다."))
        n.write(Note(title="탈것", body="자동차를 몰았다. 자동차는 빠르다."))
        n.write(Note(title="섞임", body="사과를 자동차에 실었다."))
        n.reindex()

        # 모델이 없으면 뜻 검색은 그냥 꺼져 있다 — 낱말 검색은 그대로 돈다.
        assert n.semantic("사과") == []
        assert {r["title"] for r in n.search("사과")} == {"과일", "섞임"}

        def fake(texts, prefix="query: "):
            keys = ("사과", "자동차")
            # 접두사를 꼭 받는지도 같이 본다
            assert prefix in ("query: ", "passage: "), prefix
            return [[float(t.count(k)) for k in keys] + [0.1] for t in texts]

        n.use_embedder(fake)
        assert n.embed_some(9) == 3
        assert n.embed_some(9) == 0, "다 만들었는데 또 만든다"

        # **빈 항목은 벡터를 안 만든다.** 만들면 아무 물음에나 어중간하게 가까워서
        # 1등으로 올라온다. 그래도 "다 했다"고는 해야 한다 — 안 그러면 영영 밀린다.
        n.write(Note(title="빈 것", body="", kind="note"))
        assert n.embed_some(9) == 1, "빈 항목도 한 번은 처리해야 한다"
        assert n.embed_some(9) == 0 and n.vec_left() == 0, "빈 항목이 계속 밀린다"
        assert n.conn.execute(
            "SELECT count(*) FROM vectors v JOIN notes t ON t.path = v.path "
            "WHERE trim(t.body) = ''").fetchone()[0] == 0, "빈 항목에 벡터가 생겼다"
        assert n.conn.execute("SELECT count(*) FROM vectors").fetchone()[0] >= 3

        near = [t for t, _ in n.semantic("사과 사과 사과", k=3)]
        assert near[0] == "과일", near
        assert [t for t, _ in n.semantic("자동차 자동차", k=1)] == ["탈것"]

        # **제목이 답일 때와 본문이 답일 때가 다르다.** 둘 다 두고 높은 쪽을 쓴다 —
        # 한쪽만 쓰면 다른 쪽으로 찾던 것이 통째로 빠진다.
        assert n.conn.execute(
            "SELECT count(*) FROM vectors WHERE tvec IS NULL").fetchone()[0] == 0,             "제목 벡터가 안 만들어졌다"

        # **손으로 안 이어도 뜻으로 이어진다.** 닷새를 실제로 쓴 자리에서 항목 528개에
        # 손으로 적은 이음선이 둘뿐이었다 — 잇는 일을 사람에게 맡기면 그래프는
        # 점 뿌린 판으로 남는다.
        붙음 = n.kin([r["title"] for r in n.conn.execute("SELECT title FROM notes")])
        assert 붙음, "뜻 이음선이 하나도 안 나온다"
        assert all(t not in near for t, near in 붙음.items()), "자기 자신에 이어졌다"
        # **맞짝 하나뿐이다.** 여럿을 이으면 틀린 선이 열 배로 는다(실측).
        assert all(len(near) <= 1 for near in 붙음.values()), 붙음
        # 이음선은 **양쪽 말이 같아야 한다** — 한쪽에서만 보이는 선이 있으면 안 된다.
        for t, near in 붙음.items():
            for u in near:
                assert t in 붙음.get(u, [t]), f"한쪽만 이어졌다: {t} -> {u}"
        # **마땅한 것이 없으면 빈다.** 억지로 이으면 그 틀린 하나가 유일한 하나가 되어
        # 더 눈에 띈다 — 실사용에서 「겨울 타이어 ↔ 등산 스틱」이 그랬다.
        # 모델 없이 **벡터를 손으로 놓고** 규칙만 잰다 — 검사에 쓰는 가짜 임베더는
        # 뜻이 없어서 「무엇과 무엇이 가깝다」를 물을 수가 없다.
        홀로 = Notes(Path(tmp) / "홀로")
        for 제목 in ["가깝다 하나", "가깝다 둘", "홀로 있는 것"] + [f"딴 것 {i}" for i in range(9)]:
            홀로.write(Note(title=제목, body="본문"))
        길 = {r["title"]: r["path"] for r in
              홀로.conn.execute("SELECT title, path FROM notes")}
        # **실제처럼 촘촘하게 놓는다.** 진짜 벡터는 점수가 0.86~0.90 에 뭉쳐 있어서,
        # 벌어진 값으로 시험하면 문턱이 1을 넘어 아무것도 안 이어진다. 그러면 규칙이
        # 아니라 시험 자료가 틀린 것이다.
        import math as _math

        def 방향(각):
            return [_math.cos(각), _math.sin(각), 0.0]

        붙일 = {"가깝다 하나": 방향(0.0),
                "가깝다 둘": 방향(0.10),        # 눈에 띄게 가깝다
                "홀로 있는 것": 방향(1.30)}     # 무리에서 멀찍이 — 아무도 얘를 1등으로 안 꼽는다
        for i in range(9):                      # 배경 무리 — 서로 고만고만하다
            붙일[f"딴 것 {i}"] = 방향(0.45 + i * 0.012)
        for 제목, 벡 in 붙일.items():
            홀로.conn.execute(
                "INSERT INTO vectors (path, vec, tvec) VALUES (?, ?, ?) "
                "ON CONFLICT(path) DO UPDATE SET vec = excluded.vec, tvec = excluded.tvec",
                (길[제목], _pack(벡), _pack(벡)))
        홀로.conn.commit()
        홀로._vec_cache = None
        곁 = 홀로.kin(list(붙일))
        assert 곁["가깝다 하나"] == ["가깝다 둘"], 곁
        assert 곁["가깝다 둘"] == ["가깝다 하나"], 곁      # 양쪽 말이 같다
        assert 곁["홀로 있는 것"] == [], f"짝 없는 것을 억지로 이었다: {곁}"

        # **제목만으로 가까운 것은 이웃이 아니다.** 짧은 제목은 뜻 공간에서 아무거나에
        # 가까워서, 본문이 「한 줄」뿐인 항목이 진짜 글의 이웃 자리를 뺏는다.
        # 여기서는 제목 벡터를 **아무 데나 가깝게**, 카드 벡터를 **제대로** 놓고,
        # 카드 쪽만 보는지 확인한다.
        속임 = Notes(Path(tmp) / "속임")
        for 제목 in ("글 하나", "글 둘", "빈 껍데기"):
            속임.write(Note(title=제목, body="본문"))
        자리 = {r["title"]: r["path"] for r in
                속임.conn.execute("SELECT title, path FROM notes")}
        놓기 = {
            # (카드 벡터, 제목 벡터)
            "글 하나": ([1.0, 0.0, 0.0], [0.0, 1.0, 0.0]),
            "글 둘": ([0.99, 0.14, 0.0], [0.0, 0.9, 0.436]),   # 카드는 가깝고 제목은 덜하다
            "빈 껍데기": ([0.0, 0.0, 1.0], [0.0, 1.0, 0.0]),   # 카드는 멀고 **제목만 딱 붙는다**
        }
        for 제목, (카드, 머리) in 놓기.items():
            속임.conn.execute(
                "INSERT INTO vectors (path, vec, tvec) VALUES (?, ?, ?) "
                "ON CONFLICT(path) DO UPDATE SET vec = excluded.vec, tvec = excluded.tvec",
                (자리[제목], _pack(카드), _pack(머리)))
        속임.conn.commit()
        속임._vec_cache = None
        곁 = 속임.kin(["글 하나"], 맞짝만=False)
        assert 곁["글 하나"] == ["글 둘"], f"제목만 가까운 껍데기가 이웃 자리를 뺏었다: {곁}"
        속임.conn.close()

        # **카드는 다르다.** 양쪽이 동의 안 해도 내가 꼽은 1등은 보여 준다 —
        # 갈 길이 하나도 없는 것이 어중간한 길 하나보다 나쁘다. 맞짝만 고집했더니
        # 그래프의 값을 증명했던 바로 그 항목이 다시 외딴 점이 됐다.
        길 = 홀로.kin(["홀로 있는 것"], 맞짝만=False)
        assert 길["홀로 있는 것"], f"카드에 갈 길이 하나도 없다: {길}"
        홀로.conn.close()

        # ★★ **항목이 하나뿐이면 이음선은 없다.** 자기 자신을 뺀 자리에 아무도 안
        # 남으면 `argmax` 가 자기를 도로 집어 「VC ↔ VC」가 나왔다 — 새로 깐 창고에서
        # 시험하는 쪽이 바로 봤다. 처음 켠 사람이 제일 먼저 보는 자리다.
        혼자 = Notes(Path(tmp) / "혼자")
        혼자.write(Note(title="혼자 있는 글", body="이 창고엔 나뿐이다. " * 5))
        한자리 = {r["title"]: r["path"] for r in
                 혼자.conn.execute("SELECT title, path FROM notes")}
        혼자.conn.execute(
            "INSERT INTO vectors (path, vec, tvec) VALUES (?, ?, ?)",
            (한자리["혼자 있는 글"], _pack(방향(0.3)), _pack(방향(0.3))))
        혼자.conn.commit()
        혼자._vec_cache = None
        assert 혼자.kin(["혼자 있는 글"]) == {"혼자 있는 글": []}, 혼자.kin(["혼자 있는 글"])
        assert 혼자.kin(["혼자 있는 글"], 맞짝만=False) == {"혼자 있는 글": []}, "자기를 이웃으로 꼽는다"
        혼자.conn.close()

        # 벡터가 없으면 조용히 빈손 — 뜻 검색이 꺼진 자리에서도 화면이 돌아야 한다.
        빈 = Notes(Path(tmp) / "빈자리")
        assert 빈.kin(["없는 것"]) == {}
        빈.conn.close()

        # **규칙은 한 번만 쓰고, 사람이 고치면 그대로 둔다.** 매번 덮으면 사람이 적어 둔
        # 것이 사라지고, 그러면 그 파일을 아무도 안 믿게 된다.
        규칙 = n.write_rules()
        assert 규칙 and 규칙.exists() and "이어 주는 일은 안 해도 된다" in 규칙.read_text(
            encoding="utf-8")
        규칙.write_text("사람이 고친 것", encoding="utf-8")
        n.write_rules()
        assert 규칙.read_text(encoding="utf-8") == "사람이 고친 것", "사람이 고친 것을 덮었다"
        # 규칙 파일은 **항목이 아니다** — 서식 자리에 있으니 색인이 안 센다.
        n.reindex()
        assert n.read(Path(n.RULE_FILE).stem) is None, "규칙 파일이 항목으로 셌다"

        # ★★ **규칙 글은 `wiki.py` 표에서 지어진다**(오너 2026-09-20 · 카파시 LLM Wiki 기준).
        #   코드와 글 두 군데에 적으면 갈래를 더했을 때 갈라진다 — 사람과 AI 가 다른
        #   목록을 보게 되는데, 그건 기준이 없는 것과 같다.
        # 갓 만든 창고로 잰다 — 이 검사가 도는 창고에는 옛 이름 규칙 글이 있을 수 있다
        with tempfile.TemporaryDirectory() as _새창고:
            _새 = Notes(Path(_새창고) / "notes")
            _새.write_rules()
            규칙글 = read_text(_새.template_root() / _새.RULE_FILE)
            _새.conn.close()
        for 갈 in wiki.갈래들:
            assert f"`{갈}`" in 규칙글, f"갈래 「{갈}」 이 창고의 규칙 글에 없다"
        for 일 in wiki.연산들:
            assert f"**{일}**" in 규칙글, f"일 「{일}」 이 창고의 규칙 글에 없다"
        assert 규칙글 == wiki.스키마글(), "창고에 적힌 규칙이 wiki.py 와 다르다 — 갈라졌다"

        # ★★ **층은 갈래가 정한다**(오너 2026-09-20 · 카파시 LLM Wiki 기준).
        #   `원본` 은 `raw/` 에, 나머지는 `wiki/` 에. 그 아래에 연/월이 선다.
        with tempfile.TemporaryDirectory() as _층창고:
            _층 = Notes(Path(_층창고) / "notes")
            난것 = {}
            for 갈, 제 in (("원본", "원본 글"), ("결정", "결정 글"), ("", "갈래 없는 글")):
                자리 = _층.write(Note(title=제, body="몸", kind=갈,
                                    created="2026-09-07T09:00:00Z"))
                난것[제] = 자리.relative_to(_층.root).as_posix()
            assert 난것["원본 글"].startswith("raw/2026/09/"), 난것
            assert 난것["결정 글"].startswith("wiki/2026/09/"), 난것
            # ★ 갈래를 모르면 **`wiki/`** 다 — 손 안 대는 `raw/` 에 실수로 들어가면
            #   「고치지 않는 자리」에 사람 글이 섞여 규칙이 무너진다. 일부러 적어야 raw 다.
            assert 난것["갈래 없는 글"].startswith("wiki/2026/09/"), 난것
            # 사람이 옮겨 둔 자리는 그대로 지킨다 — 층이 생겼다고 되돌리지 않는다
            옮긴곳 = _층.root / "내가정리한곳"
            옮긴곳.mkdir()
            옛자리 = _층.root / 난것["결정 글"]
            옛자리.replace(옮긴곳 / 옛자리.name)
            _층.reindex()
            글2 = _층.read("결정 글")
            assert 글2 is not None and _층.write(글2).parent.name == "내가정리한곳", "옮긴 자리를 되돌렸다"
            _층.conn.close()

        # ★ **옛 이름 규칙 글이 있으면 새로 만들지 않는다.** 사람이 고쳐 뒀을 수 있는 글을
        #   같은 자리에 둘씩 늘리면 어느 것이 규칙인지 알 수 없게 된다.
        with tempfile.TemporaryDirectory() as _옛창고:
            _옛 = Notes(Path(_옛창고) / "notes")
            _옛.template_root().mkdir(parents=True, exist_ok=True)
            # 창고를 열면 생성자가 이미 규칙 글을 만든다 — **옛 창고를 새 VC 로 여는 꼴**을
            # 만들려면 그것을 치우고 옛 이름 글만 남겨야 한다.
            (_옛.template_root() / _옛.RULE_FILE).unlink(missing_ok=True)
            (_옛.template_root() / _옛.옛RULE_FILES[0]).write_text("# 내가 고친 규칙\n", encoding="utf-8")
            _옛.write_rules()
            assert not (_옛.template_root() / _옛.RULE_FILE).exists(), (
                "옛 이름 규칙 글이 있는데 새 이름으로 또 만들었다")
            assert read_text(_옛.template_root() / _옛.옛RULE_FILES[0]) == "# 내가 고친 규칙\n"
            _옛.conn.close()

        # 낱말로 찾은 차례는 **안 흔들린다.** 뜻은 뒤에 붙기만 한다.
        plain = [r["title"] for r in n.search("사과", k=8)]
        blended = [r["title"] for r in n.search("사과", k=8)]
        assert blended[:len(plain)] == plain, (plain, blended)
        assert "탈것" not in blended, "안 걸린 것이 뜻으로 딸려 들어왔다"
        # 낱말로 몇 개 걸렸는지 따로 안다 — 화면이 「관련」이라고 우기지 않게
        assert n.낱말로찾은수 >= 1, "낱말로 걸린 것을 안 센다"
        n.search("어디에도없는말zqx", k=8)
        assert n.낱말로찾은수 == 0, "어디에도 없는 말인데 낱말로 걸렸다고 센다"

        # 좁힌 조건은 뜻으로 찾은 것에도 그대로 걸린다
        assert all(r["kind"] == "note" for r in n.search("kind:note 사과", k=8))
        # ★★ **좁힌 뒤에 세야 한다. 세고 나서 좁히면 전멸한다.** 뜻으로 뽑은 k 개를
        #   좁힘으로 걸러 내면, 그 k 개 안에 그 갈래가 없을 때 **0장**이 된다 —
        #   오너 창고(2794장·결정 120장)에서 「kind:결정 …」 이 한 장도 안 나왔다.
        #   갈래가 드문 글을 만들어 두고, 흔한 글 쪽 말로 물어도 그것이 잡히는지 본다.
        #   흔한 글은 물음과 **꼭 맞게**, 드문 글은 **살짝 덜 닮게** 적는다 —
        #   그래야 드문 글이 뜻 순위에서 확실히 뒤로 밀려 k 밖으로 나간다.
        n.write(Note(title="드문 갈래 글", body="등대 이야기다.", kind="희귀"))
        for i in range(20):
            n.write(Note(title=f"흔한 글 {i}", body="등대와 안개와 뱃길과 항해 이야기다."))
        n.reindex()
        while n.embed_some(16):
            pass
        좁힌것 = n.search("kind:희귀 등대와 안개와 뱃길과 항해", k=3)
        assert 좁힌것 and 좁힌것[0]["title"] == "드문 갈래 글",             f"좁혀 물었더니 전멸했다: {[r['title'] for r in 좁힌것]}"
        # ★★ **한 갈래가 목록을 다 차지하면 다른 갈래의 답이 영영 안 보인다.**
        #   위에서 흔한 글 20장(갈래 note)과 드문 갈래 글 1장을 넣어 뒀다.
        #   **좁히지 않고** 물어도 드문 갈래 것이 다섯 안에 들어야 한다 —
        #   오너 창고(대화 조각 2373/2794)에서 이것 하나로 찾은 물음이 6/20 → 10/20 이 됐다.
        #   ※ **낱말이 겹치면 안 된다** — 낱말로 다섯 장이 차면 뜻 검색을 아예 안 부른다.
        #     그래서 본문에 없는 말로, 뜻만 가깝게 묻는다.
        섞인것 = [r["kind"] or "note" for r in n.search("해안 불빛이 배를 이끄는 이야기", k=5)]
        assert "희귀" in 섞인것, f"한 갈래가 목록을 다 차지한다: {섞인것}"

        # 글이 바뀌면 벡터도 다시 만든다
        n.write(Note(title="과일", body="바나나로 바꿨다."))
        n.reindex()
        assert n.vec_pending(), "글이 바뀌었는데 벡터가 낡은 줄 모른다"
        n.embed_some(9)
        assert not n.vec_pending()

        # 모델을 바꾸면 벡터 크기가 달라진다(e5-small 384 → e5-base 768).
        # 섞이면 곱셈이 안 맞아 터지거나 **말없이 엉뚱한 순위**가 나온다.
        assert not n.drop_vectors_if_changed(3), "같은 크기인데 버렸다"
        assert n.drop_vectors_if_changed(768), "크기가 달라졌는데 안 버렸다"

        # ★★ **딴 크기 모델을 끼워도 찾기가 터지면 안 된다.** 화면 쪽에서만 크기를
        #   맞춰 보던 탓에 명령줄로 재는 길에서 `matmul` 이 통째로 터졌다(768 대 384).
        #   재료가 들어오는 문(`use_embedder`)에서 버리게 고쳤다 — 여기서 되돌리면 터진다.
        큰모델 = lambda 글들, 머리="": [[0.1] * 768 for _ in 글들]
        n.use_embedder(큰모델)
        n.search("아무 말이나")          # 옛 384 벡터가 남아 있으면 여기서 터졌다
        # ★ 옛 벡터는 버려졌고, **새 크기로 다시 만들어져 있거나 아직 안 만들어졌거나**
        #   둘 중 하나다(찾기가 몇 장 안 낡았으면 그 자리에서 따라잡는다). 어느 쪽이든
        #   **384 짜리가 남아 있으면 안 된다** — 그것이 섞이면 말없이 엉뚱한 순위가 된다.
        남은폭 = n.conn.execute("SELECT length(vec) FROM vectors LIMIT 1").fetchone()
        assert 남은폭 is None or 남은폭[0] == 768 * 2,             f"크기가 다른 모델을 끼웠는데 옛 벡터를 그대로 뒀다: {남은폭}"
        while n.embed_some(9):
            pass
        assert n.vec_left() == 0 and n.conn.execute(
            "SELECT length(vec) FROM vectors LIMIT 1").fetchone()[0] == 768 * 2,             "새 크기로 다시 안 만들어졌다"

        # ★★ **밖에서 고친 글은 바로 그 뜻으로 찾혀야 한다.** 옵시디언·메모장으로 고치는 것은
        #   흔한 일인데, 채우는 실은 30초마다 돈다. 그 사이에 물으면 **고치기 전 뜻**으로
        #   답한다 — 아무 표시도 없이 조용히 틀린다. 몇 장 안 낡았으면 찾는 자리에서 따라잡는다.
        _버림앞 = getattr(n, "벡터버림수", 0)
        n.use_embedder(작은모델 := (lambda 글들, 머리="": [
            [1.0 if "잠수함" in 글 else 0.0, 1.0 if "김치" in 글 else 0.0, 0.1] for 글 in 글들]))
        assert getattr(n, "벡터버림수", 0) == _버림앞 + 1, "벡터를 통째로 버리고도 말하지 않는다"
        n.write(Note(title="밖에서 고칠 글", body="김치 이야기다."))
        n.write(Note(title="딴 김치 글", body="김치 이야기다."))
        n.reindex()
        while n.embed_some(9):
            pass
        파일 = n.path_of("밖에서 고칠 글")
        파일.write_text(파일.read_text(encoding="utf-8").rstrip()
                       + chr(10) + "잠수함 이야기로 바꿨다." + chr(10), encoding="utf-8")
        n.reindex()                       # 화면·서버가 주기로 하는 일까지만
        assert n.vec_left() == 1, "밖에서 고친 것을 색인이 모른다"
        나온 = [t for t, _ in n.semantic("잠수함", k=3)]
        assert 나온 and 나온[0] == "밖에서 고칠 글",             f"밖에서 고친 뒤 낡은 뜻으로 답한다 — 조용히 틀린다: {나온}"

        # ★★ **`embed_some(1)` 로는 방금 쓴 글을 못 채운다.** `vec_pending` 의 첫 키가
        #   `used_at DESC` 라 **검색으로 읽힌 글들이 앞선다.** 빈 창고에서는 그런 글이 없어
        #   우연히 통과하는데, 실무 창고(검색을 스무 번 돌린 뒤)에서는 엉뚱한 글이 채워졌다.
        #   `embed_one` 은 그 글만 콕 집는다 — 여기서 되돌리면 터진다.
        n.conn.execute("UPDATE notes SET used_at = 1, vec_mtime = 0")
        n.conn.commit()
        n.write(Note(title="갓 쓴 글", body="이 글은 바로 벡터가 생겨야 한다."))
        갓쓴자리 = n.path_of("갓 쓴 글")
        assert n.embed_one(갓쓴자리), "갓 쓴 글의 벡터를 못 만들었다"
        assert n.conn.execute(
            "SELECT count(*) FROM vectors WHERE path = ?", (str(갓쓴자리),)).fetchone()[0] == 1,             "갓 쓴 글 말고 딴 글이 채워졌다 — 읽힌 글이 차례에서 앞선다"
        while n.embed_some(9):
            pass

        # ★★ **지운 글도 되살릴 수 있어야 한다.** 지난 판이 없는 글은 지우면 통째로
        #   사라졌다 — 지우기 전에 한 판 남긴다(5분 규칙을 건너뛴다).
        n.write(Note(title="한 번 쓰고 지울 글", body="이 글은 되살릴 수 있어야 한다."))
        assert not n.history("한 번 쓰고 지울 글"), "아직 지난 판이 있을 리 없다"
        n.delete("한 번 쓰고 지울 글")
        지난 = n.history("한 번 쓰고 지울 글")
        assert 지난, "지운 글이 통째로 사라졌다 — 되살릴 길이 없다"
        assert "되살릴 수 있어야" in 지난[0][1].read_text(encoding="utf-8"), 지난

        # 지우면 벡터도 같이 사라진다 — 유령이 검색에 남으면 안 된다
        n.delete("탈것")
        left = n.conn.execute(
            "SELECT count(*) FROM vectors v LEFT JOIN notes t ON t.path = v.path "
            "WHERE t.path IS NULL").fetchone()[0]
        assert left == 0, f"주인 없는 벡터가 {left}개 남았다"

    # --- 폴더를 옮겨도 링크가 살아 있어야 한다 ---
    # 링크·태그·별칭은 경로가 아니라 **제목**으로 묶인다. 옛 자리를 정리하면서
    # 제목으로 지우면, 새 자리에 방금 넣은 것을 지운다. 폴더 한 번 정리했을 뿐인데
    # 링크가 통째로 사라졌다(실제로 그랬다).
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "notes"
        (root / "가").mkdir(parents=True)
        (root / "가" / "회의.md").write_text("[[계획]] 얘기 #업무", encoding="utf-8")
        (root / "계획.md").write_text("계획", encoding="utf-8")
        n = Notes(root)
        cnt = lambda t: n.conn.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
        assert cnt("links") == 1 and cnt("tags") == 1

        (root / "나").mkdir()
        shutil.move(str(root / "가" / "회의.md"), str(root / "나" / "회의.md"))
        n.reindex()
        assert cnt("links") == 1, "폴더를 옮겼더니 링크가 사라졌다"
        assert cnt("tags") == 1, "폴더를 옮겼더니 태그가 사라졌다"
        assert n.neighbors("계획") == ["회의"]

        (root / "나" / "회의.md").unlink()
        n.reindex()
        assert cnt("links") == 0 and cnt("tags") == 0, "정말 지웠는데 남았다"

        # **뿌리는 절대 경로로 못 박는다.** 같은 볼트를 상대/절대로 각각 열면
        # 색인 열쇠가 달라져 매번 전부 "사라짐+새로 생김"이 된다.
        import os

        here = os.getcwd()
        try:
            os.chdir(tmp)
            rel = Notes("notes", index_now=False)
            assert rel.root == root.resolve(), (rel.root, root)
        finally:
            os.chdir(here)

    # --- 밖에서 온 이상한 파일 ---
    # **한 파일이 나머지를 통째로 죽이면 안 된다.** UTF-8 아닌 파일 하나가 색인
    # 반복문을 죽여, 그 뒤 파일들이 전부 사라진 적이 있다.
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "notes"
        root.mkdir(parents=True)
        crlf = chr(13) + chr(10)
        (root / "0깨짐.md").write_bytes(bytes([0xff, 0xfe, 0x00, 0x41, 0x20, 0xc0, 0xaf]))
        (root / "1옛한글.md").write_bytes("옛 한글 [[보통]]".encode("cp949"))
        # **BOM 이 붙은 파일도 프론트매터가 읽혀야 한다.** 윈도우 도구가 붙이는데,
        # 그냥 `utf-8` 로 읽으면 BOM 이 글자로 남아 첫 줄이 `---` 가 아니게 되고
        # **별칭·태그·종류가 통째로 사라진다** — 낯선 PC 에서 이 파일들 때문에
        # "밖에서도 고쳤길래" 안내가 헛뜨는 것으로 처음 드러났다.
        (root / "2BOM.md").write_bytes(
            ("﻿---" + crlf + 'kind: "skill"' + crlf + "aliases: 딴이름" + crlf
             + "---" + crlf + crlf + "# BOM #봄태그").encode("utf-8"))
        (root / "3CRLF.md").write_bytes(
            ("# 윈도우" + crlf + "[[보통]]" + crlf + "#태그" + crlf).encode("utf-8"))
        (root / "4빈파일.md").write_text("", encoding="utf-8")
        (root / "5보통.md").write_text("보통 글", encoding="utf-8")
        n = Notes(root)
        got = {r["title"] for r in n.conn.execute("SELECT title FROM notes")}
        # 깨진 파일 **뒤에 오는 것들이 살아 있어야** 한다. 그게 이 검사의 핵심이다.
        assert {"1옛한글", "2BOM", "3CRLF", "4빈파일", "5보통"} <= got, got
        assert "옛 한글" in n.read("1옛한글").body, "cp949 파일을 못 읽는다"
        assert n.read("4빈파일") is not None, "빈 파일도 항목이다"
        # 줄바꿈이 CR+LF 여도 링크·태그가 잡혀야 한다
        assert "3CRLF" in [s for s, _ in n.backlinks("보통")], n.backlinks("보통")
        assert n.read("3CRLF").tags() == ["태그"], n.read("3CRLF").tags()
        bom = n.read("2BOM")
        assert bom.kind == "skill", f"BOM 때문에 프론트매터가 안 읽힌다: {bom.kind}"
        assert bom.aliases == ["딴이름"], bom.aliases
        assert not bom.body.startswith("﻿"), "BOM 이 글자로 남았다"
        assert n.resolve("딴이름") == "2BOM", n.resolve("딴이름")

    # --- 사람이 잠가 둔 파일 ---
    # 죽으면 쓰던 글이 사라진다. 곁에 남기고 알린다.
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "notes"
        root.mkdir(parents=True)
        locked = root / "잠김.md"
        locked.write_text("건드리지 마", encoding="utf-8")
        n = Notes(root)
        # ★★ **「잠근다」가 운영체제마다 다르다.** 윈도우는 읽기 전용이면 자리 바꾸기가
        #   막히는데, **맥·리눅스는 안 막힌다** — 원자적 쓰기는 `os.replace` 라 파일이
        #   아니라 **폴더** 권한만 보기 때문이다. 맥에서 그대로 재니 잠근 글이 그냥
        #   덮여 썼다. 맥에서 사람이 실제로 잠그는 길(Finder 「잠금」)은 `uchg` 플래그라,
        #   그걸 쓴다 — 덮어쓰기도 바꿔치기도 막히면서 **폴더는 그대로라 곁에는 남는다.**
        os.chmod(locked, stat.S_IREAD)
        if os.name != "nt":
            os.chflags(locked, stat.UF_IMMUTABLE)
        try:
            try:
                n.write(Note(title="잠김", body="바꿔보기"))
                raise AssertionError("잠긴 파일에 썼다고 한다")
            except WriteBlocked:
                pass
            assert locked.read_text(encoding="utf-8") == "건드리지 마", "원본이 바뀌었다"
            beside = list(root.rglob("*못 쓴 글*"))
            assert beside and "바꿔보기" in beside[0].read_text(encoding="utf-8"),                 "쓰던 글을 잃었다"
        finally:
            if os.name != "nt":
                os.chflags(locked, 0)
            os.chmod(locked, stat.S_IWRITE)

    # --- 동시에 만지기 ---
    # 화면·AI·옵시디언이 같은 볼트를 함께 쓴다. **한쪽이 지우는 사이 다른 쪽이 그
    # 파일을 만지면** 실이 통째로 죽었다 — 여럿이 쓰면 반드시 생긴다.
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "notes"
        n = Notes(root, str(Path(tmp) / "idx.db"))
        for i in range(8):
            n.write(Note(title=f"글{i}", body=f"[[글{(i + 1) % 8}]] #태그"))
        n.reindex()

        died = []
        stop = time.time() + 2.0

        def churn():
            me = Notes(root, str(Path(tmp) / "idx.db"), index_now=False)
            rng = random.Random(1)
            try:
                while time.time() < stop:
                    t = f"뜨내기{rng.randrange(4)}"
                    pick = rng.random()
                    if pick < .4:
                        me.write(Note(title=t, body="[[글0]]"))
                    elif pick < .7:
                        me.delete(t)
                    else:
                        me.rename(t, f"뜨내기{rng.randrange(4)}")
            except Exception:
                died.append(traceback.format_exc(limit=3))
            finally:
                me.conn.close()

        def scan():
            me = Notes(root, str(Path(tmp) / "idx.db"), index_now=False)
            try:
                while time.time() < stop:
                    me.reindex()
                    me.read("글0")
                    me.backlinks("글0")
            except Exception:
                died.append(traceback.format_exc(limit=3))
            finally:
                me.conn.close()

        threads = [threading.Thread(target=churn), threading.Thread(target=scan)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(20)
        assert not died, died[0]

        # 어지럽힌 뒤에도 색인과 파일이 맞아야 한다
        n.reindex()
        files = {str(p) for p in n.notes_files()}
        rows = {r["path"] for r in n.conn.execute("SELECT path FROM notes")}
        assert files == rows, (len(files), len(rows))
        for table, col in (("links", "src"), ("tags", "title")):
            left = n.conn.execute(
                f"SELECT count(*) FROM {table} x LEFT JOIN notes t ON t.title = x.{col} "
                "WHERE t.title IS NULL").fetchone()[0]
            assert left == 0, f"주인 없는 {table} {left}개"
        assert not list(root.rglob("*.tmp")), "임시 파일이 남았다"
        n.conn.close()   # 윈도우는 열린 파일을 못 지운다

    # --- 무작위로 두들기기 ---
    # 사람이 짜는 검사는 늘 **자기가 생각한 길만** 밟는다. 무작위 순서로 섞어
    # 돌리면서 불변식만 본다. 씨앗을 박아 둬서 깨지면 똑같이 재현된다.
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "notes"
        n = Notes(root, str(Path(tmp) / "idx.db"))
        n.use_embedder(lambda texts, prefix="query: ": [[float(len(t)), 1.0] for t in texts])
        rng = random.Random(20260828)
        names = ["회의", "계약서: 검토/1차", "C# 메모", "🌋 화산", "  앞뒤  ", "가" * 90, "END."]
        live: list[str] = []
        for step in range(120):
            what = rng.choice(["쓰기", "쓰기", "지우기", "이름", "옮기기", "밖에서", "훑기", "벡터"])
            try:
                if what == "쓰기":
                    t = rng.choice(names) + (f" {rng.randrange(9)}" if rng.random() < .5 else "")
                    n.write(Note(title=t, body=f"[[{rng.choice(live or [t])}]] #태그{rng.randrange(3)}"))
                    if t not in live:
                        live.append(t)
                elif what == "지우기" and live:
                    t = rng.choice(live)
                    if n.delete(t):
                        live.remove(t)
                elif what == "이름" and live:
                    a = rng.choice(live)
                    b = rng.choice(names) + f" {rng.randrange(9)}"
                    if n.rename(a, b):
                        live.remove(a)
                        live.append(b)
                elif what == "옮기기" and live:
                    src = n.path_of(rng.choice(live))
                    if src.exists():
                        d = root / rng.choice(["가", "나/다"])
                        d.mkdir(parents=True, exist_ok=True)
                        if not (d / src.name).exists():
                            shutil.move(str(src), str(d / src.name))
                elif what == "밖에서":
                    (root / f"밖{step}.md").write_bytes(rng.choice([
                        b"", bytes([0xff, 0xfe, 0x20, 0x41]),
                        "옛한글 [[회의]]".encode("cp949"),
                        ("# 제목" + chr(13) + chr(10) + "#태그" + chr(13) + chr(10)).encode()]))
                elif what == "벡터":
                    n.embed_some(4)
                else:
                    n.reindex()
            except WriteBlocked:
                pass                     # 알려 주는 것이 정상이다
        n.reindex()
        files = {str(p) for p in n.notes_files()}
        rows = {r["path"] for r in n.conn.execute("SELECT path FROM notes")}
        assert files == rows, (len(files), len(rows), list(rows - files)[:2])
        for table, col in (("links", "src"), ("tags", "title")):
            left = n.conn.execute(
                f"SELECT count(*) FROM {table} x LEFT JOIN notes t ON t.title = x.{col} "
                "WHERE t.title IS NULL").fetchone()[0]
            assert left == 0, f"주인 없는 {table} {left}개"
        left = n.conn.execute(
            "SELECT count(*) FROM vectors v LEFT JOIN notes t ON t.path = v.path "
            "WHERE t.path IS NULL").fetchone()[0]
        assert left == 0, f"주인 없는 벡터 {left}개"
        assert n.conn.execute("SELECT count(*) FROM search").fetchone()[0] == len(rows)
        assert not list(root.rglob("*.tmp")), "임시 파일이 남았다"
        n.conn.close()

    # **"어제 쓴 것" 같은 지시가 쓸 수 있어야 한다.** 만든 때가 아니라 고친 때로 본다 —
    # 3년 전에 만들어 어제 고친 글도 사람에게는 "어제 쓴 것"이다.
    with tempfile.TemporaryDirectory() as tmp:
        n = Notes(Path(tmp) / "notes")
        n.write(Note(title="오늘 것", body="지금 쓴다"))
        오늘 = [t for t, _, _ in n.written_when("오늘")]
        assert "오늘 것" in 오늘, 오늘
        assert n.written_when("없는말") == [], "모르는 때는 빈손이어야 한다"
        옛것 = n.path_of("오늘 것")
        n.conn.execute("UPDATE notes SET mtime = ? WHERE path = ?",
                       (time.time() - 86400 * 3, str(옛것)))
        n.conn.commit()
        assert "오늘 것" not in [t for t, _, _ in n.written_when("오늘")], "사흘 전 것이 오늘로 잡힌다"

    # **쓰던 색인을 이어받아도 살아야 한다.** 스키마에 칸을 늘렸는데 「지금 모양」
    # 집합을 안 고쳐, 이어 쓰는 사람은 검색이 통째로 죽었다
    # (`no such column: v.tvec`). 빠져나올 길도 없었다 — 되살릴 스위치까지 같은
    # 칸을 읽다 먼저 죽었다. 옛 색인을 손으로 만들어 그 자리를 지킨다.
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "notes"
        root.mkdir(parents=True)
        (root / "옛글.md").write_text("옛날 글이다", encoding="utf-8")
        index = str(Path(tmp) / "옛색인.db")
        n = Notes(root, index)
        n.conn.close()

        # 옛 판이 만들어 둔 모양으로 되돌린다 — 제목 벡터 칸이 없다.
        import sqlite3 as sq

        db = sq.connect(index)
        db.execute("DROP TABLE vectors")
        db.execute("CREATE TABLE vectors (path TEXT PRIMARY KEY, vec BLOB NOT NULL)")
        db.execute("INSERT INTO vectors (path, vec) VALUES (?, ?)",
                   (str(root / "옛글.md"), bytes(16)))
        db.commit()
        db.close()

        n = Notes(root, index)
        cols = {r[1] for r in n.conn.execute("PRAGMA table_info(vectors)")}
        assert "tvec" in cols, cols
        assert n.search("옛날") , "이어받은 색인에서 찾기가 죽는다"
        assert n.vec_left() > 0, "다시 만들 거리가 있어야 한다"
        n.conn.close()          # 윈도우는 열린 파일을 못 지운다

    # **벡터가 빠진 항목은 스스로 되살아나야 한다.** 본문이 있는데 벡터가 없고
    # 「아직 못 만든 것」에도 안 잡히면 그 항목은 영영 뜻 검색에서 빠지고, 사람은
    # 알 길이 없다. 그리고 「본문이 빈 항목」을 셀 때 SQLite 의 `trim()` 은 공백만
    # 떼고 줄바꿈은 안 뗀다 — 빈 줄만 있는 항목이 안 세어졌다.
    with tempfile.TemporaryDirectory() as tmp:
        index = str(Path(tmp) / "치유.db")
        n = Notes(Path(tmp) / "notes", index)
        n.write(Note(title="알맹이 있는 글", body="여기 내용이 있다"))
        n.write(Note(title="빈 글", body=chr(10) * 2))
        assert n.blank_count() == 1, n.blank_count()

        # 벡터가 있는 척 표시만 해 두고 벡터는 없앤다 — 그 판에서 났던 그 꼴이다.
        n.conn.execute("DELETE FROM vectors")
        n.conn.execute("UPDATE notes SET vec_mtime = mtime")
        n.conn.commit()
        assert n.vec_left() == 0, "표시가 다 붙은 상태여야 시험이 된다"
        n.conn.close()

        # **켤 때 저절로 되살아나야 한다.** 손으로 불러서 되는 것만 봐서는,
        # 켜는 길에 안 이어져 있어도 검사가 초록불이다.
        again = Notes(Path(tmp) / "notes", index, index_now=False)
        남은 = again.vec_left()
        assert 남은 == 1, f"켤 때 알맹이 있는 글 하나가 되살아나야 한다: {남은}"
        again.conn.close()

    # **찾은 것에 같은 항목이 두 번 나오면 안 된다.** 낱말 색인에 같은 파일이 두 줄
    # 들어가면 조인이 두 줄로 돌려준다 — 낯선 PC 에서 2등과 4등에 같은 글이 나왔다.
    # 개수만 견주는 옛 고침은 「하나 겹치고 하나 빠진」 꼴을 못 잡았다.
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "notes"
        index = str(Path(tmp) / "겹침.db")
        n = Notes(root, index)
        n.write(Note(title="설비 보수", body="빠뜨린 것이 없는지 한 번 더 본다"))
        n.write(Note(title="재고 정리", body="빠뜨린 것이 없는지 한 번 더 본다"))
        if n.fts:
            # 한 줄을 더 넣고 한 줄을 뺀다 — 개수는 그대로라 옛 고침이 못 잡던 꼴이다.
            얹을 = n.conn.execute(
                "SELECT path, title, body FROM notes WHERE title = '설비 보수'").fetchone()
            n.conn.execute("DELETE FROM search WHERE title = '재고 정리'")
            n.conn.execute("INSERT INTO search (path, title, body) VALUES (?, ?, ?)",
                           (얹을["path"], 얹을["title"], 얹을["body"]))
            n.conn.commit()
            찾음 = [r["title"] for r in n.search("빠뜨린 것")]
            assert len(찾음) == len(set(찾음)), f"같은 것이 두 번 나온다: {찾음}"
            n.conn.close()

            # 켤 때 낱말 색인이 저절로 고쳐져야 한다 — 그물만으로는 원인이 남는다.
            n = Notes(root, index, index_now=False)
            겹침 = n.conn.execute(
                "SELECT count(*) - count(DISTINCT path) FROM search").fetchone()[0]
            assert 겹침 == 0, f"낱말 색인에 겹친 줄이 남았다: {겹침}"
        n.conn.close()

    # ── 본문에 사람이 적은 앞머리는 진짜 앞머리로 올라간다 ─────────────────
    # ★ 안 올리면 `---` 블록이 두 겹이 되고, 옵시디언은 첫 블록만 속성으로 읽어
    #   사람이 적은 type/date/status 가 **본문 글자**가 된다(시험 쪽 라-①).
    #   검색 미리보기가 그걸로 채워져 무슨 글인지 안 보이고, AI 는 `type:` 으로
    #   걸러 회상하지 못한다 — 이 창고는 AI 의 바깥 기억이라 그게 더 아프다.
    with tempfile.TemporaryDirectory() as tmp:
        n = Notes(Path(tmp) / "notes", str(Path(tmp) / "i.db"), index_now=False)
        속 = ("---" + chr(10) + "type: 시험" + chr(10) + "status: 진행"
              + chr(10) + "---" + chr(10) + "본문이다.")
        길 = n.write(Note(title="앞머리시험", body=속))
        글 =길.read_text(encoding="utf-8")
        assert 글.count(chr(10) + "---") == 1, "앞머리가 두 겹이다" + chr(10) + 글
        되읽음 = n.read("앞머리시험")
        assert (되읽음.extra or {}).get("type") == "시험", 되읽음.extra
        assert (되읽음.extra or {}).get("status") == "진행", 되읽음.extra
        # 본문은 앞머리를 뺀 알맹이만 — 미리보기 첫 줄이 여기서 나온다
        assert 되읽음.body.strip() == "본문이다.", repr(되읽음.body)
        # 우리 신원은 사람 글이 못 덮는다
        속2 = "---" + chr(10) + 'id: "가짜"' + chr(10) + "---" + chr(10) + "몸"
        n.write(Note(title="신원시험", body=속2))
        assert n.read("신원시험").id != "가짜", "사람 글이 신원을 덮었다"
        # 그냥 가로줄로 시작하는 글은 안 건드린다
        가로 = "---" + chr(10) + "이건 앞머리가 아니라 그냥 줄이다." + chr(10) + "---"
        n.write(Note(title="가로줄시험", body=가로))
        assert "이건 앞머리가 아니라" in n.read("가로줄시험").body, "가로줄을 앞머리로 먹었다"
        n.conn.close()

    # ── 제목이 물음과 똑같으면 그것부터 ─────────────────────────────────────
    # ★ bm25 가 제목을 12배로 쳐도 **거의 같은 형제 제목**한테 진다. 실사용에서
    #   「안 먹는 말투」를 물으면 그 제목의 글이 3등이었다(시험 쪽 새-①).
    #   실측(항목 3142개): 제목 그대로 물었을 때 1등이 93% → 100%,
    #   제목과 안 똑같은 물음 59개는 차례가 **하나도 안 바뀌었다.**
    with tempfile.TemporaryDirectory() as tmp:
        n = Notes(Path(tmp) / "notes", str(Path(tmp) / "i.db"), index_now=False)
        # 형제 제목이 본문에서 더 자주 나오게 해 둔다 — 이게 없으면 자료가 두 답을 안 가른다
        n.write(Note(title="안 먹는 말투", body="이 글은 짧다."))
        n.write(Note(title="안 먹는 말투 정리 보고",
                     body=("안 먹는 말투 " * 30) + "여러 번 나온다."))
        n.reindex()
        났 = [r["title"] for r in n.search("안 먹는 말투", k=5)]
        assert 났 and 났[0] == "안 먹는 말투", 났
        # 똑같은 제목이 없으면 아무것도 안 당긴다 — 그때 차례는 원래대로다
        그냥 = [r["title"] for r in n.search("말투", k=5)]
        assert "안 먹는 말투" in 그냥 or "안 먹는 말투 정리 보고" in 그냥, 그냥
        n.conn.close()

    # ── 따옴표는 좁힌다. 뜻 검색이 도로 채우면 안 된다 ─────────────────────
    # ★ 실사용에서 `"소리 내어 읽으면"` 과 따옴표 없는 물음의 결과가 목록도 순서도
    #   똑같이 나왔다(시험 쪽 ⑥). 낱말로 좁힌 자리를 뜻 검색이 채워서다.
    #   **좁히라고 친 것을 넓히면 따옴표가 아무 일도 안 한 것처럼 보인다.**
    with tempfile.TemporaryDirectory() as tmp:
        n = Notes(Path(tmp) / "notes", str(Path(tmp) / "i.db"), index_now=False)
        n.write(Note(title="구절 든 글", body="이 글에는 소리 내어 읽으면 이 든다."))
        n.write(Note(title="말만 든 글", body="소리도 나고 읽으면 좋고 내어 준다."))
        n.reindex()
        try:
            느슨 = [r["title"] for r in n.search("소리 내어 읽으면", k=5)]
            굳게 = [r["title"] for r in n.search('"소리 내어 읽으면"', k=5)]
            assert "구절 든 글" in 굳게, 굳게
            # ★ 따옴표를 쳐도 제목 우선이 살아 있어야 한다. 처음엔 물음 글자를
            #   그대로 견줘서 `"제목"` 이 따옴표째라 안 맞았고, **따옴표를 붙이면
            #   제목 우선이 조용히 꺼졌다.** 사람은 정확히 원할수록 따옴표를 친다.
            n.write(Note(title="소리 내어 읽으면", body="이건 그 제목의 글이다."))
            n.write(Note(title="딴 글인데 그 말이 많다",
                         body=("소리 내어 읽으면 " * 20) + "여러 번 나온다."))
            n.reindex()
            for 물음 in ("소리 내어 읽으면", '"소리 내어 읽으면"'):
                난 = [r["title"] for r in n.search(물음, k=5)]
                assert 난 and 난[0] == "소리 내어 읽으면", (물음, 난)
            assert "말만 든 글" not in 굳게, "따옴표가 안 좁혔다: " + str(굳게)
            assert len(굳게) < len(느슨), (느슨, 굳게)
        # ★ 위 둘만으로는 **자료가 두 답을 안 가른다** — 이 작은 자리엔 뜻 검색이
        #   안 물려 있어 채울 일 자체가 없다. 그래서 뜻 검색을 **가짜로 물려** 잰다:
        #   따옴표를 쳤으면 뜻이 무엇을 내놓든 **한 줄도 안 붙어야** 한다.
            n.semantic = lambda q, k=8: [("말만 든 글", 0.99)]
            굳게2 = [r["title"] for r in n.search('"소리 내어 읽으면"', k=5)]
            assert "말만 든 글" not in 굳게2,                 "따옴표를 쳤는데 뜻 검색이 도로 채웠다: " + str(굳게2)
            느슨2 = [r["title"] for r in n.search("없는말 소리", k=5)]
            assert "말만 든 글" in 느슨2, "따옴표가 없으면 뜻으로 채워야 한다: " + str(느슨2)
        finally:
            # ★ 터져도 DB 는 닫는다. 안 닫으면 임시폴더 정리가 실패하면서
            #   **그 오류가 진짜 오류를 덮는다** — 실제로 한 번 덮었다.
            n.conn.close()

    # ── 흐린 선: 흡수 글의 [[ ]] 도 넣되 갈라서 넣는다 ─────────────────────
    # ★ 예전에는 아예 안 넣었다. 진한 선(사람이 이은 것)의 뜻을 지키려던 것인데,
    #   실제 자료가 사실상 전부 흡수분이라 **그물이 통째로 비었다**(3142장에 이음 0).
    #   「유기적으로 연결하는 지식창고」가 1번의 정의인데 연결이 0이었다.
    # 정리 실패를 눈감는다 — 못 지운 임시 파일의 오류가 **진짜 오류를 덮은** 적이 있다.
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        n = Notes(Path(tmp) / "notes", str(Path(tmp) / "i.db"), index_now=False)
        try:
            n.write(Note(title="사람 글", body="[[가나]] 를 가리킨다"))
            n.write(Note(title="흡수 글", body="[[다라]] 를 가리킨다",
                         extra={"지은이": "문지기"}))
            n.reindex()
            난 = {r[0]: r[2] for r in
                  n.conn.execute("SELECT src, dst, 흐림 FROM links").fetchall()}
            assert 난.get("사람 글") == 0, 난
            assert 난.get("흡수 글") == 1, ("흡수 글의 [[ ]] 가 안 들어갔거나 진한 선이다", 난)
        finally:
            n.conn.close()

    # ── 밖에서 온 글은 5분 규칙을 건너뛰고 반드시 남는다 ────────────────────
    # ★ 「치는 대로 저장」이라 5분 안이면 지난 판을 안 만드는데, 그 사이에 **사람이
    #   옵시디언에서 고친 판**이 들어오면 흔적 없이 사라진다. 되돌릴 수도, 사라진
    #   줄 알 수도 없다. 우리가 쓴 지문과 다르면 남의 손이므로 반드시 남긴다.
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        뿌리 = Path(tmp) / "notes"
        n = Notes(뿌리, str(Path(tmp) / "i.db"), index_now=False)
        try:
            길 = n.write(Note(title="겹침 시험", body="처음 글"))
            # ★ **먼저 지난 판을 하나 만들어 둔다.** 지난 판이 없으면 5분 규칙이
            #   발동조차 안 해서 **자료가 두 답을 안 가른다** — 처음엔 이걸 빠뜨려
            #   고침을 빼도 검사가 통과했다.
            n.write(Note(title="겹침 시험", body="두 번째 글"))
            assert list((뿌리 / HISTORY_DIR).rglob("*.md")), "지난 판이 안 생겼다"
            # 이제 5분 안이다. 사람이 밖에서 고친 척 — 원래는 안 남던 자리다
            길.write_text(길.read_text(encoding="utf-8")
                          .replace("두 번째 글", "사람이 고친 글"), encoding="utf-8")
            n.write(Note(title="겹침 시험", body="AI 가 덮어쓴 글"))
            판들 = list((뿌리 / HISTORY_DIR).rglob("*.md"))
            assert any("사람이 고친 글" in f.read_text(encoding="utf-8") for f in 판들),                 "밖에서 온 글이 5분 규칙에 걸려 사라졌다"
            # 우리가 쓴 것을 우리가 또 쓰는 것은 남의 손이 아니다
            assert not n._남의손인가(길, 길.read_text(encoding="utf-8")), "제 글을 남의 손으로 봤다"
            # ★ 지문이 없으면 **모르는 것이므로 남의 손으로 친다**
            n.conn.execute("UPDATE notes SET wrote = ''")
            n.conn.commit()
            assert n._남의손인가(길, 길.read_text(encoding="utf-8")),                 "지문이 없는데 안전으로 읽었다"
        finally:
            n.conn.close()

    # ── 이름 바꾸기는 하다 만 것을 남긴다 ──────────────────────────────────
    # ★ 이름 바꾸기는 **여러 파일**을 건드리는데 `os.replace` 의 원자성은 한 파일까지다.
    #   중간에 죽으면 그물이 반쯤 끊긴 채로 남고 **끊긴 줄조차 모른다.**
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        n = Notes(Path(tmp) / "notes", str(Path(tmp) / "i.db"), index_now=False)
        try:
            n.write(Note(title="옛 이름", body="몸"))
            n.write(Note(title="가리키는 글", body="[[옛 이름]] 을 본다"))
            n.reindex()
            assert n.이름바꾸다만것() is None, "하기도 전에 쪽지가 있다"
            assert n.rename("옛 이름", "새 이름")
            assert "[[새 이름]]" in n.read("가리키는 글").body, "역링크가 안 따라왔다"
            assert n.이름바꾸다만것() is None, "끝났는데 쪽지가 남았다"
            # ★★ **이름만 바꾸는 것이지 딴 것을 버리는 게 아니다.**
            #   예전엔 `extra` 를 통째로 버려 `출처`·`지은이` 와 사람이 적은
            #   `type`·`status` 가 다 사라졌다. **원본 사실이라 되살릴 수 없다** —
            #   이름 바꾼 35개가 흡수분인데 사람이 만든 글로 보이게 됐고,
            #   다시 붓기 막이가 그걸 보고 막아섰다.
            n.write(Note(title="딸린 것 시험", body="몸", kind="일",
                         aliases=["별명"],
                         extra={"출처": "a.md", "지은이": "문지기", "type": "시험"}))
            assert n.rename("딸린 것 시험", "딸린 것 시험 2")
            옮 = n.read("딸린 것 시험 2")
            for 열쇠, 값 in (("출처", "a.md"), ("지은이", "문지기"), ("type", "시험")):
                assert (옮.extra or {}).get(열쇠) == 값, (열쇠, 옮.extra)
            assert 옮.aliases == ["별명"], 옮.aliases
            assert 옮.kind == "일", 옮.kind
            # 하다 만 상태를 흉내 내면 켤 때 알아본다
            (Path(tmp) / "vc-이름바꾸다만것.txt").write_text(
                "가" + chr(9) + "나", encoding="utf-8")
            assert n.이름바꾸다만것() == ("가", "나"), n.이름바꾸다만것()
        finally:
            n.conn.close()

    # ── ★★ 쓰던 색인 위에 올려 쓰는 길 ────────────────────────────────────
    #
    # **이걸 안 재서 남의 기록을 깼다.** `CREATE TABLE IF NOT EXISTS` 는 **이미 있는
    # 표를 안 고친다** — 새로 만든 색인에만 칸이 생기고 쓰던 색인에는 안 생긴다.
    # 「links 표에 흐림 칸이 없다」로 **새 글 쓰기가 통째로 죽었는데**, 만든 쪽은
    # 기록을 새로 부어서(빈 색인) 한 번도 못 봤다.
    #
    # **새로 만드는 길만 재고 올려 쓰는 길을 안 밟은 것이다.** 쓰는 사람은 늘
    # 올려 쓴다 — 새로 만드는 쪽이 오히려 드문 길이다.
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        터 = Path(tmp)
        옛색인 = str(터 / "옛.db")
        옛 = sqlite3.connect(옛색인)
        옛.executescript(
            "CREATE TABLE notes(path TEXT PRIMARY KEY, id TEXT NOT NULL, "
            "title TEXT NOT NULL, kind TEXT NOT NULL DEFAULT 'note', "
            "pinned INTEGER NOT NULL DEFAULT 0, created TEXT NOT NULL DEFAULT '', "
            "mtime REAL NOT NULL DEFAULT 0, body TEXT NOT NULL DEFAULT '', "
            "used_at REAL NOT NULL DEFAULT 0, use_count INTEGER NOT NULL DEFAULT 0);"
            "CREATE TABLE links(src TEXT NOT NULL, dst TEXT NOT NULL, "
            "heading TEXT NOT NULL DEFAULT '', PRIMARY KEY(src, dst, heading));")
        옛.commit()
        옛.close()
        n = Notes(터 / "notes", 옛색인, index_now=False)
        try:
            # 여기서 터지던 자리다 — 「table links has no column named 흐림」
            n.write(Note(title="옛 색인에 새 글", body="[[가나]] 를 가리킨다"))
            칸 = {r[1] for r in n.conn.execute("PRAGMA table_info(links)")}
            assert "흐림" in 칸, f"쓰던 색인에 흐림 칸이 안 붙었다: {칸}"
            칸2 = {r[1] for r in n.conn.execute("PRAGMA table_info(notes)")}
            assert "wrote" in 칸2, f"쓰던 색인에 wrote 칸이 안 붙었다: {칸2}"
            # 읽는 쪽도 성해야 한다 — 진단이 「색인 읽기 실패」로 떨어지던 자리다
            assert n.conn.execute(
                "SELECT count(*) FROM links WHERE 흐림 = 1").fetchone()[0] >= 0
        finally:
            n.conn.close()

    print("notes self-check 통과")


if __name__ == "__main__":
    _self_check()
