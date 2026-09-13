"""학습 로그와 제안 저장소 (결정 17·18).

SQLite를 쓴다. 단일 사용자·단일 프로세스이므로 DB 서버를 세울 이유가 없다.

기억(항목)은 여기 없다. 마크다운 파일이 원본이고 notes.py가 담당한다(결정 30).
저장소를 두 곳에 두면 어느 쪽이 진짜인지 모르게 되므로, 기억은 notes.py에만 있다.
"""

from __future__ import annotations
import paths

import json
import sqlite3
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS log_events (
    id             INTEGER PRIMARY KEY,
    instruction_id TEXT NOT NULL,
    seq            INTEGER NOT NULL,
    ts             TEXT NOT NULL,
    phase          TEXT NOT NULL,
    tier           TEXT NOT NULL,
    outcome        TEXT NOT NULL,
    module         TEXT,
    step           TEXT,
    latency_ms     INTEGER,
    tokens_in      INTEGER,
    tokens_out     INTEGER,
    cost_krw       REAL NOT NULL DEFAULT 0,
    retries        INTEGER NOT NULL DEFAULT 0,
    clarify_count  INTEGER NOT NULL DEFAULT 0,
    failure_point  TEXT,
    detail         TEXT NOT NULL DEFAULT '{}',
    UNIQUE (instruction_id, seq)
);
CREATE INDEX IF NOT EXISTS idx_log_instruction ON log_events (instruction_id);
CREATE INDEX IF NOT EXISTS idx_log_outcome ON log_events (outcome, ts);

CREATE TABLE IF NOT EXISTS proposals (
    proposal_id TEXT PRIMARY KEY,
    ts          REAL NOT NULL,
    type        TEXT NOT NULL,
    title       TEXT NOT NULL,
    summary     TEXT NOT NULL,
    based_on    TEXT NOT NULL DEFAULT '[]',
    declaration TEXT NOT NULL DEFAULT '{}',
    decision    TEXT
);
"""


class Store:
    def __init__(self, path: str | Path = "") -> None:
        # 기본 자리를 여기서 정한다. 부르는 쪽마다 정하게 두면 **한 곳을 놓쳤을 때
        # 설치 폴더에 파일이 샌다** — 실제로 서버 쪽 한 줄을 놓쳐서 그랬다.
        path = path or paths.store_path()
        # ★★ **기록 db 가 깨져도 켜져야 한다.** 전원이 나가 깨지면 `DatabaseError` 로 프로그램이
        #   안 켜졌다(재 봤다). 지우지 않고 `.깨짐-<시각>` 으로 옆에 치우고 새로 연다 — 잠김 같은
        #   일시 오류(OperationalError)는 깨짐이 아니다.
        try:
            self._열기(path)
        except sqlite3.OperationalError:
            raise
        except sqlite3.DatabaseError as 깨짐:
            try:
                self.conn.close()
            except Exception:
                pass
            if str(path) != ":memory:":
                때 = time.strftime("%Y%m%d-%H%M%S")
                for 곁 in ("", "-wal", "-shm"):
                    자리 = Path(str(path) + 곁)
                    if 자리.exists():
                        try:
                            자리.replace(Path(f"{path}.깨짐-{때}{곁}"))
                        except OSError:
                            pass
            print(f"[기록] 깨져서 옆에 치우고 새로 연다: {Path(str(path)).name} ({type(깨짐).__name__})")
            try:
                import report

                report.trail(f"[기록] 깨져서 옆에 치우고 새로 연다: {Path(str(path)).name}")
            except Exception:
                pass
            self._열기(path)

    def _열기(self, path) -> None:
        self.conn = sqlite3.connect(path, check_same_thread=False)
        # 학습 로그도 서버와 화면이 같이 쓴다 — WAL이라야 서로 안 막는다.
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA busy_timeout=8000")
        # 학습 로그도 색인과 같다 — 잃어도 파일·기록에서 다시 만든다.
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    # --- 학습 로그 -------------------------------------------------------

    def add_log(self, event: Any) -> None:
        """같은 (instruction_id, seq)가 다시 와도 조용히 무시한다.

        폰이 PC 꺼짐 구간을 버퍼에 쌓았다가 재전송하므로 중복이 정상적으로 발생한다.
        """
        row = asdict(event) if not isinstance(event, dict) else dict(event)
        row["detail"] = json.dumps(row.get("detail") or {}, ensure_ascii=False)
        cols = ", ".join(row)
        marks = ", ".join(f":{k}" for k in row)
        self.conn.execute(
            f"INSERT OR IGNORE INTO log_events ({cols}) VALUES ({marks})", row
        )
        self.conn.commit()

    def instruction(self, instruction_id: str) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM log_events WHERE instruction_id = ? ORDER BY seq",
            (instruction_id,),
        ).fetchall()

    def recent(self, limit: int = 12) -> list[sqlite3.Row]:
        """최근 활동을 새것부터. 화면의 활동 흐름이 이걸 그대로 쓴다."""
        return self.conn.execute(
            "SELECT * FROM log_events ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()

    def failures(self, limit: int = 50) -> list[sqlite3.Row]:
        """PC의 분석기가 먹을 재료. 실패가 곧 다음 스킬의 씨앗이다(결정 17)."""
        return self.conn.execute(
            "SELECT * FROM log_events WHERE outcome = 'failure' ORDER BY ts DESC LIMIT ?",
            (limit,),
        ).fetchall()

    # --- 제안 -----------------------------------------------------------

    def add_proposal(self, p: Any) -> None:
        row = asdict(p) if not isinstance(p, dict) else dict(p)
        row["based_on"] = json.dumps(row.get("based_on") or [], ensure_ascii=False)
        row["declaration"] = json.dumps(row.get("declaration") or {}, ensure_ascii=False)
        row["ts"] = time.time()
        self.conn.execute(
            "INSERT OR REPLACE INTO proposals "
            "(proposal_id, ts, type, title, summary, based_on, declaration) "
            "VALUES (:proposal_id, :ts, :type, :title, :summary, :based_on, :declaration)",
            row,
        )
        self.conn.commit()

    def same_proposal_pending(self, type_: str, title: str) -> bool:
        """같은 제안이 이미 대기 중인지. 분석을 돌릴 때마다 같은 걸 또 띄우면 소음이 된다."""
        return self.conn.execute(
            "SELECT 1 FROM proposals WHERE type = ? AND title = ? AND decision IS NULL",
            (type_, title),
        ).fetchone() is not None

    def proposal(self, proposal_id: str) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM proposals WHERE proposal_id = ?", (proposal_id,)
        ).fetchone()

    def pending_proposals(self) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM proposals WHERE decision IS NULL ORDER BY ts"
        ).fetchall()

    def decide(self, proposal_id: str, decision: str) -> bool:
        cur = self.conn.execute(
            "UPDATE proposals SET decision = ? WHERE proposal_id = ?",
            (decision, proposal_id),
        )
        self.conn.commit()
        return cur.rowcount > 0


def _self_check() -> None:
    s = Store(":memory:")

    e = dict(
        instruction_id="01J",
        seq=1,
        ts="2026-08-05T00:00:00.000Z",
        phase="module_run",
        tier="pc",
        outcome="success",
        module="product_search",
        step=None,
        latency_ms=820,
        tokens_in=10,
        tokens_out=5,
        cost_krw=0.0,
        retries=0,
        clarify_count=0,
        failure_point=None,
        detail={},
    )
    s.add_log(e)
    s.add_log(e)  # 재전송 중복
    assert len(s.instruction("01J")) == 1, "중복 재전송이 두 줄로 들어갔다"

    s.add_log({**e, "seq": 2, "outcome": "failure", "failure_point": "vision_query"})
    assert s.failures()[0]["failure_point"] == "vision_query"

    s.add_proposal(
        dict(proposal_id="p1", type="skill_proposal", title="출근 준비", summary="아침 브리핑")
    )
    assert len(s.pending_proposals()) == 1
    assert s.decide("p1", "approve") is True
    assert s.pending_proposals() == []
    assert s.decide("없음", "approve") is False

    assert [r["seq"] for r in s.recent(2)] == [2, 1], "최근 활동이 새것부터 안 나온다"

    # ★★ 깨진 기록 db 에서도 켜져야 한다(전원이 나가면 안 켜졌다).
    import tempfile as _tf3
    with _tf3.TemporaryDirectory() as _곳:
        _자리 = Path(_곳) / "eb.db"
        _s = Store(str(_자리)); _s.conn.close()
        _자리.write_bytes(b"garbage!" * 20 + _자리.read_bytes()[160:])
        for _곁 in ("-wal", "-shm"):
            Path(str(_자리) + _곁).unlink(missing_ok=True)
        _s2 = Store(str(_자리))
        assert _s2.recent(1) == [], "깨진 기록 db 를 새로 열지 못했다"
        assert list(Path(_곳).glob("eb.db.깨짐-*")), "깨진 기록 db 를 옆에 안 치웠다"
        _s2.conn.close()
    print("store self-check 통과")


if __name__ == "__main__":
    _self_check()
