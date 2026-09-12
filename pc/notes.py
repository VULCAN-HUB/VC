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

import json
import os
import random
import re
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
LINK_RE = re.compile(r"\[\[([^\]\[|#]+?)(?:#([^\]\[|]+))?(?:\|([^\]\[]+))?\]\]")

# ![[노트]] · ![[노트#소제목]] — 끼워 보기. 링크와 같은 꼴이라 연결로도 잡힌다.
EMBED_RE = re.compile(r"!\[\[([^\]\[|#]+?)(?:#([^\]\[|]+))?(?:\|[^\]\[]+)?\]\]")

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
UNSAFE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

# 첨부로 보는 확장자. **첨부는 항목이 아니다** — `![[사진.png]]`을 노트 링크로 세면
# "아직 없는 것"에 사진 이름이 끝없이 쌓이고 그래프에 유령 점이 생긴다.
ATTACH_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg", ".pdf"}
ATTACH_DIR = "_첨부"

# 지난 판을 두는 곳. 점으로 시작해 **옵시디언에서 안 보인다** — 기계가 챙기는 것이지
# 사람이 뒤적일 폴더가 아니다. 색인에서도 통째로 뺀다.
HISTORY_DIR = ".이력"
HISTORY_KEEP = 20          # 항목당 남길 판 수. 20년이라도 무한정 쌓으면 안 된다
HISTORY_GAP_SEC = 300      # 이 안에 또 저장되면 새 판을 안 만든다(치는 대로 저장이라)

# 서식(템플릿)을 두는 곳. 밑줄로 시작해 항목 목록에서 눈에 안 띄되, 사람이 열어
# 고칠 수 있게 **보이는** 폴더로 둔다(`_첨부`와 같은 자리).
TEMPLATE_DIR = "_서식"

# 서식 안에서 갈아 끼우는 자리. 옵시디언 표기도 같이 받는다.
SLOT_RE = re.compile(r"\{\{\s*(날짜|시각|제목|date|time|title)\s*\}\}", re.I)          # 노트 폴더 안. `_`로 시작해 항목 폴더와 눈으로 갈린다


# `#0E1116` 같은 색상 코드. 3·4·6·8자리 16진수는 태그로 안 센다.
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
NARROW = {
    "tag": "태그", "태그": "태그",
    "path": "경로", "경로": "경로",
    "kind": "종류", "종류": "종류",
    "year": "해", "해": "해", "년": "해",
}


class Ask:
    """물음을 뜯어 놓은 것. 낱말·구절·좁히는 말·뺄 것."""

    __slots__ = ("terms", "phrases", "narrow", "minus_terms", "minus_phrases", "raw")

    def __init__(self, raw: str) -> None:
        self.raw = raw
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
        out = " AND ".join(want)
        drop = ['"%s"*' % t for t in self.minus_terms]
        drop += ['"%s"' % p.replace('"', "") for p in self.minus_phrases]
        if drop:
            gone = " OR ".join(drop)
            out = f"({out}) NOT ({gone})" if out else ""
        return out
HEX_COLOR = re.compile(r"(?i)[0-9a-f]{3}|[0-9a-f]{4}|[0-9a-f]{6}|[0-9a-f]{8}")


def is_attachment(name: str) -> bool:
    return Path(name).suffix.lower() in ATTACH_EXT


INDEX_SCHEMA = """
CREATE TABLE IF NOT EXISTS notes (
    path      TEXT PRIMARY KEY,
    id        TEXT NOT NULL,
    title     TEXT NOT NULL,
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
NARROW = {
    "tag": "태그", "태그": "태그",
    "path": "경로", "경로": "경로",
    "kind": "종류", "종류": "종류",
    "year": "해", "해": "해", "년": "해",
}


class Ask:
    """물음을 뜯어 놓은 것. 낱말·구절·좁히는 말·뺄 것."""

    __slots__ = ("terms", "phrases", "narrow", "minus_terms", "minus_phrases", "raw")

    def __init__(self, raw: str) -> None:
        self.raw = raw
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
        out = " AND ".join(want)
        drop = ['"%s"*' % t for t in self.minus_terms]
        drop += ['"%s"' % p.replace('"', "") for p in self.minus_phrases]
        if drop:
            gone = " OR ".join(drop)
            out = f"({out}) NOT ({gone})" if out else ""
        return out
HEX_COLOR = re.compile(r"(?i)[0-9a-f]{3}|[0-9a-f]{4}|[0-9a-f]{6}|[0-9a-f]{8}")


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
    for 열쇠 in ("요약", "summary", "description", "설명"):
        값 = (extra or {}).get(열쇠)
        if isinstance(값, str) and 값.strip():
            return 값.strip()[:길이]
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
        낱말 = [w for w in re.split(r"[^0-9A-Za-z가-힣]+", 물음) if len(w) >= 2]
        if 낱말:
            점수 = [(sum(1 for w in 낱말 if w in 줄), -i, 줄)
                    for i, 줄 in enumerate(줄들)]
            맞은, _, 고른 = max(점수)
            if 맞은:
                return 고른[:길이]
    return 첫줄[:길이]


def parse_links(body: str) -> list[tuple[str, str]]:
    """본문에서 (대상, 소제목)을 뽑는다. 보이는 글자는 연결과 무관해서 버린다.

    첨부(`![[사진.png]]`)는 뺀다 — 항목이 아니라 파일이다.
    """
    return [(m.group(1).strip(), (m.group(2) or "").strip())
            for m in LINK_RE.finditer(body)
            if m.group(1).strip() and not is_attachment(m.group(1).strip())]


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


def section(body: str, heading: str) -> str:
    """소제목 아래 한 토막만 잘라 온다.

    `![[보고서#8월 정산]]`으로 부르면 보고서 전체가 아니라 그 자리만 보여야 한다.
    다음 소제목이 같거나 더 높은 층이면 거기서 끊는다 — 하위 소제목은 그 토막에 속한다.
    """
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
        tmp.write_text(text, encoding="utf-8")
        for wait in (0, 0.01, 0.02, 0.05, 0.1, 0.2, 0.4):
            if wait:
                time.sleep(wait)
            try:
                os.replace(tmp, path)
                return
            except PermissionError:
                continue
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
        finally:
            tmp.unlink(missing_ok=True)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def safe_title(title: str) -> str:
    """제목을 파일명으로 쓴다. 옵시디언에서 [[제목]]으로 이어지려면 이름이 곧 식별자다."""
    cleaned = UNSAFE.sub("-", title).strip().strip(".")
    return cleaned[:80] or "무제"


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
        return parse_tags(self.body)

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
        lines = [f"{k}: {json.dumps(v, ensure_ascii=False)}" for k, v in front.items()]
        return "---\n" + "\n".join(lines) + "\n---\n" + self.body.rstrip() + "\n"

    @classmethod
    def loads(cls, title: str, raw: str) -> Note:
        m = FRONTMATTER_RE.match(raw)
        if not m:
            # 사용자가 손으로 만든 파일. 그대로 받아들인다.
            return cls(title=title, body=raw, created=_now())
        front: dict[str, object] = {}
        for line in m.group(1).splitlines():
            if ":" not in line:
                continue
            k, _, v = line.partition(":")
            try:
                front[k.strip()] = json.loads(v.strip())
            except json.JSONDecodeError:
                front[k.strip()] = v.strip()
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
        for junk in self.root.rglob("*.tmp"):
            junk.unlink(missing_ok=True)  # 쓰다 죽으면 남는다. 항목으로 세면 안 된다
        self.index_path = index      # 딴 실이 제 연결을 열 때 쓴다
        self.conn = sqlite3.connect(index, check_same_thread=False)
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
        """항목으로 세면 안 되는 자리. 지난 판과 서식은 글이지 항목이 아니다."""
        return HISTORY_DIR in path.parts or TEMPLATE_DIR in path.parts

    def notes_files(self):
        """항목 파일만. 지난 판은 항목이 아니다 — 세면 항목 수가 스무 배가 된다."""
        for path in self.root.rglob("*.md"):
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
        # 밀리초까지 넣는다. 초까지만 쓰면 같은 초에 두 번 저장될 때 앞 판이 조용히
        # 덮여 사라진다.
        stamp = time.strftime("%Y%m%d-%H%M%S") + f"-{int(time.time() * 1000) % 1000:03d}"
        _atomic_write(folder / f"{stamp}.md", old)
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
        try:
            self.keep_history(path, read_text(path), always=True)
        except (Vanished, OSError):
            pass
        self.write(old)
        return True

    # --- 오늘 일지 · 서식 ------------------------------------------------

    def daily(self, day: str = "") -> Note:
        """오늘(또는 그날) 일지. 없으면 만든다.

        제목이 곧 날짜다(`2026-08-27`). 해마다 폴더가 갈리므로 20년이 쌓여도
        한 폴더에 몰리지 않는다.
        """
        day = day or time.strftime("%Y-%m-%d")
        got = self.read(day)
        if got is not None:
            return got
        body = self.fill_slots(self.template("일지"), day) or f"# {day}" + chr(10)
        note = Note(title=day, body=body, kind="note")
        self.write(note)
        return note

    # 이 저장소를 만지는 모두(사람·AI·나중에 붙을 무엇이든)가 읽을 규칙. 항목으로는
    # 안 세는 자리(`_서식`)에 둔다.
    RULE_FILE = "이 폴더를 만지는 규칙.md"
    RULES = """# 이 폴더를 만지는 규칙

이 파일은 VC 가 처음 한 번만 만든다. 사람이 고쳐도 되고 지워도 된다 — 다시 안 만든다.

## 1. 이어 주는 일은 안 해도 된다

**`[[제목]]` 을 일부러 넣을 필요가 없다.** VC 가 뜻으로 가까운 것을 스스로 이어
그래프와 「비슷한 것」 줄에 보여 준다. 그 이음선은 **파일에 안 적힌다** — 셈해서 그릴
뿐이라 틀려도 글이 더러워지지 않는다.

`[[제목]]` 은 **사람이 「이것과 저것은 이어진다」고 말하고 싶을 때만** 쓴다.
그 선은 진하게, 짐작한 선은 흐리게 그려져 눈으로 갈린다.

> 그래서 이 규칙은 **아무것도 안 하는 것이 지키는 것**이다. 무엇이 붙어도 못 어긴다.

## 2. 글은 그냥 마크다운이다

앞머리(`---`)는 있어도 되고 없어도 된다. 없으면 VC 가 알아서 채운다.
`kind` 는 `agent · skill · preference · place · thing · note` 중 하나이고, 모르는 값을
적어도 **지우지 않고 그대로 둔다.**

## 3. 건드리면 안 되는 자리

- `.이력/` — 지난 판. VC 가 관리한다
- `_첨부/` — 붙임 파일
- `_서식/` — 서식과 이 규칙. **항목으로 안 센다**

## 4. 색인은 언제나 버려도 된다

`.md` 가 원본이고 색인(`notes_index.db`)은 그것을 훑어 만든 것뿐이다.
어긋난 것 같으면 `VC.exe --색인다시`. 기록은 안 건드린다.
"""

    def write_rules(self) -> Path | None:
        """규칙 파일을 **한 번만** 만든다. 이미 있으면 안 건드린다."""
        where = self.template_root() / self.RULE_FILE
        try:
            if where.exists():
                return where
            where.parent.mkdir(parents=True, exist_ok=True)
            _atomic_write(where, self.RULES)
        except (OSError, WriteBlocked):
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
            return sorted(f.stem for f in folder.glob("*.md"))
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
        except Exception:
            return        # 모델이 시원찮으면 뜻 검색만 꺼진다. 찾기는 살아야 한다
        self.drop_vectors_if_changed(width)
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
        got = self._vectors()
        if embed is None or got is None or not text.strip():
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

    def path_of(self, title: str, created: str = "") -> Path:
        """항목의 파일 자리.

        **이미 있으면 그 자리를 그대로 쓴다.** 사람이 옮겨 둔 폴더를 저장할 때마다
        되돌리면, 정리해 둔 것이 매번 흐트러진다.

        새로 만드는 것은 `연/월` 폴더에 넣는다. 20년치를 한 폴더에 쌓으면 탐색기도
        옵시디언도 버거워진다. 훑는 속도는 폴더를 나눠도 같지만(실측), 사람이 열어
        볼 때가 다르다.
        """
        row = self.conn.execute(
            "SELECT path FROM notes WHERE title = ? ORDER BY mtime DESC LIMIT 1",
            (title,)).fetchone()
        if row and Path(row["path"]).exists():
            return Path(row["path"])
        stamp = (created or _now())[:7]              # YYYY-MM
        year, _, month = stamp.partition("-")
        folder = self.root / year / month if year.isdigit() else self.root
        folder.mkdir(parents=True, exist_ok=True)
        return folder / f"{safe_title(title)}.md"

    def write(self, note: Note, at: str | Path = "") -> Path:
        """항목을 쓴다. **이미 있으면 신원(식별자·만든 날짜)을 물려받는다.**

        `at`을 주면 **그 파일**에 쓴다. 같은 제목이 두 폴더에 있을 때 제목으로 자리를
        다시 찾으면 2027년 것을 열어 놓고 2026년 파일에 저장하게 된다.

        AI가 같은 제목으로 다시 쓸 때마다 식별자와 만든 날짜가 새로 생기면, 20년 뒤에
        "이건 언제 처음 적은 거지"에 답할 수 없다.
        """
        old = self.read_at(at) if at else self.read(note.title)
        if old is not None:
            note.id = note.id or old.id
            note.created = note.created or old.created
        # 사람이 본문에 적은 `---` 블록을 진짜 앞머리로 올린다. 안 하면 두 겹이 된다.
        note.본문앞머리끌어올리기()
        note.id = note.id or f"{int(time.time() * 1000):x}"
        note.created = note.created or _now()
        path = Path(at) if at else self.path_of(note.title, note.created)
        fresh = note.dumps()
        # 덮어쓰기 전에 지난 판을 남긴다. **내용이 같으면 안 남긴다** — 안 바뀐 저장이
        # 판만 늘리면 정작 되돌리고 싶은 지점이 밀려나 사라진다.
        if path.exists():
            try:
                was = read_text(path)
            except (Vanished, OSError):
                was = fresh    # 사라졌으면 남길 지난 판도 없다
            if was != fresh:
                # ★★ **밖에서 온 글은 5분 규칙에 안 걸리게 한다.**
                # 「치는 대로 저장」이라 판이 너무 늘지 않게 5분 안이면 지난 판을
                # 안 만드는데, 그 사이에 **사람이 옵시디언에서 고친 판**이 들어오면
                # 그것이 흔적 없이 사라진다. 되돌릴 수도, 사라진 줄 알 수도 없다.
                # 우리가 쓴 지문과 다르면 남의 손이 닿은 것이므로 **반드시 남긴다.**
                self.keep_history(path, was, always=self._남의손인가(path, was))
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

    def append(self, title: str, text: str, kind: str = "note") -> Path:
        """있으면 뒤에 붙이고, 없으면 새로 만든다.

        AI가 관찰을 쌓는 기본 방식이다. 덮어쓰기를 기본으로 하면 어제 적은 것이
        오늘 적은 것에 조용히 지워진다 — 기억이 아니라 최신값 저장소가 된다.
        """
        old = self.read(title)
        if old is None:
            return self.write(Note(title=title, body=text, kind=kind))
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
        rows = self.conn.execute(
            "SELECT path FROM notes WHERE title = ? ORDER BY path", (title,)).fetchall()
        return [Path(r["path"]) for r in rows] if len(rows) > 1 else []

    def read(self, title: str) -> Note | None:
        path = self.path_of(title)
        if not path.exists():
            return None
        try:
            return Note.loads(path.stem, read_text(path))
        except Vanished:
            return None      # 읽는 사이 남이 지웠다

    def delete(self, title: str) -> bool:
        path = self.path_of(title)
        if not path.exists():
            return False
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
        known = {
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
            stem = Path(gone).stem
            self._drop_search(gone)
            self.conn.execute("DELETE FROM notes WHERE path = ?", (gone,))
            # **같은 제목이 아직 살아 있으면 딸린 것을 안 지운다.**
            #
            # 링크·태그·별칭은 경로가 아니라 **제목**으로 묶여 있다. 그래서 파일을
            # 다른 폴더로 옮기면, 새 자리에 방금 넣은 링크를 옛 자리 정리가 지웠다 —
            # 폴더 한 번 정리했을 뿐인데 링크가 통째로 사라진다.
            still = self.conn.execute(
                "SELECT 1 FROM notes WHERE title = ? LIMIT 1", (stem,)).fetchone()
            if still is None:
                self.conn.execute("DELETE FROM links WHERE src = ?", (stem,))
                self.conn.execute("DELETE FROM tags WHERE title = ?", (stem,))
                self.conn.execute("DELETE FROM aliases WHERE title = ?", (stem,))
            changed += 1
        self.conn.commit()
        return changed

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

    def attachment_path(self, name: str) -> Path | None:
        """이름으로 첨부 파일을 찾는다. 없으면 None."""
        if not is_attachment(name):
            return None
        hit = next(self.attach_root().rglob(safe_title(name)), None)
        if hit is None:                       # 사람이 다른 데 둔 경우까지 훑는다
            hit = next((p for p in self.root.rglob(safe_title(name))
                        if p.is_file() and not self._is_history(p)), None)
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
        if commit:
            self.conn.commit()

    # --- 조회 -----------------------------------------------------------

    #  좁히는 말이 걸리는 곳. 값 하나를 물음표로 받는다.
    _NARROW_SQL = {
        "태그": "EXISTS (SELECT 1 FROM tags g WHERE g.title = n.title AND g.tag LIKE ?)",
        "경로": "n.path LIKE ?",
        "종류": "n.kind = ?",
        "해": "substr(n.created, 1, 4) = ?",
    }
    _NARROW_ARG = {
        "태그": lambda v: v.lstrip("#") + "%",
        "경로": lambda v: f"%{v}%",
        "종류": lambda v: v,
        "해": lambda v: v,
    }

    def _narrow_sql(self, narrow: list[tuple[str, str]]) -> tuple[list[str], list[str]]:
        """좁히는 말을 SQL 조건으로. 모르는 이름은 조용히 버린다."""
        where, args = [], []
        for kind, value in narrow:
            drop = kind.startswith("빼기:")
            base = kind[3:] if drop else kind
            sql = self._NARROW_SQL.get(base)
            if sql is None:
                continue
            where.append(f"NOT ({sql})" if drop else sql)
            args.append(self._NARROW_ARG[base](value))
        return where, args

    def search(self, q: str, k: int = 8) -> list[sqlite3.Row]:
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
        ask = Ask(q)
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
                "SELECT * FROM notes WHERE title LIKE ? OR body LIKE ? "
                "ORDER BY pinned DESC, created DESC LIMIT ?",
                (f"%{q}%", f"%{q}%", k),
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
        if rows:
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
        like = f"%{part}%"
        head = f"{part}%"
        rows = self.conn.execute(
            "SELECT title AS name, (title = ?) AS same, (title LIKE ?) AS head, use_count "
            "  FROM notes WHERE title LIKE ? "
            "UNION ALL "
            "SELECT alias AS name, (alias = ?) AS same, (alias LIKE ?) AS head, 0 "
            "  FROM aliases WHERE alias LIKE ? "
            "ORDER BY same DESC, head DESC, use_count DESC, name LIMIT ?",
            (part, head, like, part, head, like, k),
        ).fetchall()
        return list(dict.fromkeys(r["name"] for r in rows))

    def rename(self, old: str, new: str) -> bool:
        """항목 이름을 바꾸고 **그것을 가리키던 링크도 같이 고친다.**

        파일만 바꾸면 다른 노트의 `[[옛이름]]`이 허공을 가리켜 그래프에서 연결이
        통째로 끊긴다. 이름은 곧 열쇠라, 옮길 때는 가리키는 쪽도 같이 옮겨야 한다.

        새 이름이 이미 있으면 안 바꾼다 — 덮어쓰면 기록이 사라진다.
        """
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
            except OSError:
                pass          # 못 옮겨도 이름 바꾸기 자체는 살린다
        mark = f"[[{old}]]"
        for path in self.notes_files():   # 하위 폴더까지
            # 훑는 동안 남이 지울 수 있다. 한 파일 때문에 **나머지 링크가 안 고쳐지면**
            # 그래프가 반쯤 끊긴 채로 남는다 — 그게 더 나쁘다.
            try:
                text = read_text(path)
            except (Vanished, OSError):
                continue
            if mark in text:
                try:
                    _atomic_write(path, text.replace(mark, f"[[{new}]]"))
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
        alias = [r["alias"] for r in self.conn.execute(
            "SELECT alias FROM aliases WHERE title = ?", (title,))]
        return [title, *alias]

    def neighbors(self, title: str) -> list[str]:
        """그래프 화면이 쓸 연결. 나가는 링크와 들어오는 링크를 함께 준다.

        나가는 링크는 **가리키는 실제 항목으로 바꿔서** 준다. 별칭으로 걸린 링크가
        따로 떨어진 점으로 보이면 그래프가 두 배로 부푼다. 아직 없는 항목을 가리키는
        링크(미해결)는 여기서 뺀다 — 없는 것과 이을 수는 없다.
        """
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

        # 화면에 올릴 것 고르기 — 20년치를 다 그릴 수는 없다.
        n.write(Note(title="고정된 것", body="", pinned=True))
        picked = n.working_set(3, keep={"보고서"})
        assert "보고서" in picked, "반드시 넣으랬는데 잘렸다"
        assert len(picked) == 3
        assert n.working_set(2)[0] == "고정된 것", "고정한 게 먼저 안 온다"
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
        assert n.attachment_path("없는사진.png") is None
        assert not is_attachment("그냥 항목")

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
        assert got("path:notes") >= {"배포 준비"}, got("path:notes")
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
        assert [t for t in n.templates() if t != Path(n.RULE_FILE).stem]             == ["일지", "회의록"], n.templates()
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

    # --- 뜻으로 찾기 ---
    # **모델 없이 검사한다.** 자체점검이 모델 파일에 매이면, 모델이 없는 PC에서는
    # 검사 자체를 못 돌린다.
    # 소제목 **뒤에서 시작하는** 조각이 생길 만큼 길어야 이름표를 확인할 수 있다.
    # 뜻을 재는 글은 **제목 + 앞부분**이다. 더 넣으면 오히려 못 맞힌다(위 표).
    card = meaning_card("회의록", "가" * 5000)
    assert card.startswith("회의록" + chr(10))
    assert len(card) == len("회의록") + 1 + CARD_CHARS, len(card)
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
        assert n.vec_left() > 0, "크기가 다른 모델을 끼웠는데 옛 벡터를 그대로 뒀다"
        assert n.conn.execute("SELECT count(*) FROM vectors").fetchone()[0] == 0
        assert n.vec_left() > 0, "버렸으면 다시 만들 거리가 있어야 한다"
        while n.embed_some(9):
            pass

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
        os.chmod(locked, stat.S_IREAD)
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
