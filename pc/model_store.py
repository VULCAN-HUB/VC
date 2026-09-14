"""모델 받기 — 앱 안에서 (결정 42).

사용자가 파일을 직접 찾아 `models/`에 넣게 하면 대부분은 안 한다. 사양에 맞는 것을
목록으로 보여주고 눌러서 받게 한다.

**주소는 코드에 든 목록에서만 온다.** 사용자가 아무 주소나 넣게 하지 않는다 — 모델 파일은
실행되는 코드에 가까워서, 검증된 배포처(공식 저장소)만 열어 둔다.

받는 규칙 넷:

    .part로 받고 다 받은 뒤 이름을 바꾼다   중간에 끊긴 파일이 모델 목록에 뜨면 안 된다
    크기를 확인한다                        덜 받힌 파일은 로딩할 때 알 수 없는 오류가 난다
    비전은 짝(mmproj)까지 받아야 완료다      본체만 있으면 사진을 못 본다
    언제든 멈출 수 있다                     몇 GB짜리라 잘못 눌렀을 때 되돌릴 길이 필요하다

쪼개진 파일(`-00001-of-00002`)은 목록에 안 넣는다. 우리 로더가 단일 파일만 받는다.
"""

from __future__ import annotations

import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

HF = "https://huggingface.co"


@dataclass
class Entry:
    """받을 수 있는 모델 하나. `needs_vram`은 권장이지 금지가 아니다 —
    모자라면 경고만 하고, 실제로 굴릴지는 사용자가 정한다."""

    key: str
    role: str
    label: str
    url: str
    size_mb: int
    needs_vram: int = 0
    pair_url: str = ""  # 비전 모델의 mmproj
    pair_size_mb: int = 0
    extra_url: str = ""  # Piper의 설정 json 같은 곁다리
    note: str = ""

    @property
    def total_mb(self) -> int:
        return self.size_mb + self.pair_size_mb


# 2026-08-08에 HEAD 요청으로 존재와 크기를 확인한 것들만 넣는다.
CATALOG: tuple[Entry, ...] = (
    Entry("qwen2.5-1.5b", "chat", "Qwen2.5 1.5B (가벼움)",
          f"{HF}/Qwen/Qwen2.5-1.5B-Instruct-GGUF/resolve/main/qwen2.5-1.5b-instruct-q4_k_m.gguf",
          1117, needs_vram=2000, note="어느 PC에서나 돈다. CPU로도 쓸 만하다"),
    Entry("qwen3-4b", "chat", "Qwen3 4B (중간)",
          f"{HF}/Qwen/Qwen3-4B-GGUF/resolve/main/Qwen3-4B-Q4_K_M.gguf",
          2497, needs_vram=4000, note="4GB부터. 답이 눈에 띄게 낫다"),
    Entry("qwen3-8b", "chat", "Qwen3 8B (큼)",
          f"{HF}/Qwen/Qwen3-8B-GGUF/resolve/main/Qwen3-8B-Q4_K_M.gguf",
          5030, needs_vram=8000, note="8GB 이상 권장"),
    Entry("qwen2.5-vl-3b", "vision", "Qwen2.5-VL 3B (사진)",
          f"{HF}/ggml-org/Qwen2.5-VL-3B-Instruct-GGUF/resolve/main/Qwen2.5-VL-3B-Instruct-Q4_K_M.gguf",
          1930, needs_vram=6000,
          pair_url=f"{HF}/ggml-org/Qwen2.5-VL-3B-Instruct-GGUF/resolve/main/mmproj-Qwen2.5-VL-3B-Instruct-Q8_0.gguf",
          pair_size_mb=845, note="4GB에서는 CPU로 밀려 느리다"),
    Entry("qwen2.5-vl-7b", "vision", "Qwen2.5-VL 7B (사진, 정확)",
          f"{HF}/ggml-org/Qwen2.5-VL-7B-Instruct-GGUF/resolve/main/Qwen2.5-VL-7B-Instruct-Q4_K_M.gguf",
          4683, needs_vram=12000,
          pair_url=f"{HF}/ggml-org/Qwen2.5-VL-7B-Instruct-GGUF/resolve/main/mmproj-Qwen2.5-VL-7B-Instruct-Q8_0.gguf",
          pair_size_mb=853, note="12GB 이상 권장"),
    # 뜻 검색을 더 잘하게. 설치본에 딸린 것은 e5-small(118MB)이고, 이건 그보다 큰
    # 대신 정확하다 — 정답을 아는 물음 12개로 재보니 **3등 안이 8→10**이었다
    # (2026-08-28 실측). 못 찾던 것을 찾는다.
    # ★ [잰 것, 2026-09-13] 오너 창고 2794장·얼린 물음 20개로 다시 재니
    #   **찾은 물음 10 → 12**. 찾는 속도는 거의 같고(0.5 → 0.7초) 벡터를 처음 만드는
    #   데만 2.5배 든다(84 → 206초, 한 번뿐이다).
    #   ※ 예전에 「큰 모델도 못 줄인다(14→14)」고 적어 둔 적이 있는데 **그건 낡은 벡터
    #     위에서 잰 값이라 무효다.** 잣대를 다시 세우고 나서 값이 뒤집혔다.
    Entry("e5-base", "meaning", "뜻 검색 — 큰 모델 (정확)",
          f"{HF}/Xenova/multilingual-e5-base/resolve/main/onnx/model_quantized.onnx",
          279,
          pair_url=f"{HF}/Xenova/multilingual-e5-base/resolve/main/tokenizer.json",
          pair_size_mb=17,
          note="딸린 것보다 정확하다(3등 안 8→10). 벡터를 처음부터 다시 만든다"),
    Entry("ko-kss", "voice", "한국어 목소리 (kss)",
          f"{HF}/rhasspy/piper-voices/resolve/main/ko/ko_KR/kss/medium/ko_KR-kss-medium.onnx",
          63, extra_url=f"{HF}/rhasspy/piper-voices/resolve/main/ko/ko_KR/kss/medium/ko_KR-kss-medium.onnx.json",
          note="Piper 신경망 음성. 합성이 실시간의 7배"),
)


def find(key: str) -> Entry | None:
    return next((e for e in CATALOG if e.key == key), None)


def target_paths(entry: Entry, model_dir: str | Path) -> list[tuple[str, Path]]:
    """(주소, 저장 위치) 목록. 이름은 **우리 규칙**으로 바꿔 저장한다 —
    비전 모델의 짝을 이름으로 찾기 때문에 원본 파일명을 그대로 쓰면 안 된다."""
    root = Path(model_dir)
    if entry.role == "meaning":
        # 딸려 온 것을 덮어쓰지 않는다 — 받은 것이 나쁘면 되돌아갈 자리가 있어야 한다.
        base = root / entry.key
        out = [(entry.url, base / "model.onnx")]
        if entry.pair_url:
            out.append((entry.pair_url, base / "tokenizer.json"))
        return out

    if entry.role == "voice":
        base = root / "piper" / f"{entry.key}.onnx"
        out = [(entry.url, base)]
        if entry.extra_url:
            out.append((entry.extra_url, base.with_suffix(".onnx.json")))
        return out

    out = [(entry.url, root / f"{entry.key}.gguf")]
    if entry.pair_url:
        out.append((entry.pair_url, root / f"{entry.key}.mmproj.gguf"))
    return out


def have(entry: Entry, model_dir: str | Path) -> bool:
    """짝까지 다 있어야 있는 것이다. 본체만 있으면 사진을 못 본다."""
    return all(p.is_file() for _, p in target_paths(entry, model_dir))


@dataclass
class Progress:
    key: str = ""
    label: str = ""
    done_mb: float = 0.0
    total_mb: float = 0.0
    state: str = "idle"  # idle | downloading | done | failed | cancelled
    error: str = ""
    started: float = field(default_factory=time.time)

    @property
    def percent(self) -> int:
        return int(self.done_mb / self.total_mb * 100) if self.total_mb else 0


class Downloader:
    """한 번에 하나만 받는다. 여러 개를 동시에 받으면 둘 다 느리고 진행이 안 보인다."""

    CHUNK = 1 << 20  # 1MB

    def __init__(self, model_dir: str | Path = "../models") -> None:
        self.model_dir = Path(model_dir)
        self.progress = Progress()
        self._cancel = threading.Event()
        self._thread: threading.Thread | None = None
        self._opener: Callable[..., Any] = urllib.request.urlopen  # 검사에서 갈아 끼운다
        self.sweep_parts()

    def sweep_parts(self) -> int:
        """받다 만 조각을 치운다.

        정상 취소·실패는 스스로 지우지만 **앱이 강제 종료되면 못 지운다**(실제로 겪었다).
        켤 때 한 번 쓸어야 몇 GB가 조용히 쌓이지 않는다. 이어받기는 지원하지 않는다 —
        중간부터 받으려면 서버가 Range를 지원하는지·파일이 그대로인지 확인해야 하는데,
        모델 파일은 한 번 더 받는 편이 검증보다 싸다.
        """
        gone = 0
        for folder in (self.model_dir, self.model_dir / "piper"):
            if not folder.is_dir():
                continue
            for part in folder.glob("*.part"):
                try:
                    part.unlink()
                    gone += 1
                except OSError:
                    pass
        return gone

    @property
    def busy(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, key: str) -> bool:
        if self.busy:
            return False
        entry = find(key)
        if entry is None:
            return False
        self._cancel.clear()
        self.progress = Progress(key=key, label=entry.label, state="downloading",
                                 total_mb=float(entry.total_mb))
        self._thread = threading.Thread(target=self._run, args=(entry,), daemon=True)
        self._thread.start()
        return True

    def cancel(self) -> None:
        """몇 GB짜리라 잘못 눌렀을 때 되돌릴 길이 있어야 한다."""
        self._cancel.set()

    def _run(self, entry: Entry) -> None:
        parts: list[Path] = []
        try:
            for url, dest in target_paths(entry, self.model_dir):
                if dest.is_file():
                    self.progress.done_mb += dest.stat().st_size / 1e6
                    continue
                dest.parent.mkdir(parents=True, exist_ok=True)
                part = dest.with_suffix(dest.suffix + ".part")
                parts.append(part)
                self._fetch(url, part)
                if self._cancel.is_set():
                    raise InterruptedError
                part.replace(dest)  # 다 받은 뒤에만 진짜 이름을 준다
                parts.remove(part)
            self.progress.state = "done"
        except InterruptedError:
            self.progress.state = "cancelled"
        except Exception as e:
            self.progress.state = "failed"
            self.progress.error = str(e)[:200]
        finally:
            # 중간에 끊긴 조각은 지운다. 남겨두면 다음에 뭐가 뭔지 모른다.
            for part in parts:
                try:
                    part.unlink()
                except OSError:
                    pass

    def _fetch(self, url: str, part: Path) -> None:
        req = urllib.request.Request(url, headers={"User-Agent": "EB/1.0"})
        with self._opener(req, timeout=60) as resp, part.open("wb") as f:
            expected = int(resp.headers.get("Content-Length") or 0)
            got = 0
            while True:
                if self._cancel.is_set():
                    raise InterruptedError
                chunk = resp.read(self.CHUNK)
                if not chunk:
                    break
                f.write(chunk)
                got += len(chunk)
                self.progress.done_mb += len(chunk) / 1e6
        # 덜 받힌 파일은 로딩할 때 알 수 없는 오류로 나타난다. 여기서 잡는다.
        if expected and got != expected:
            raise OSError(f"덜 받았다: {got}/{expected} 바이트")


def listing(model_dir: str | Path = "../models", vram_mb: int = 0,
            also: str | Path | None = None) -> list[dict]:
    """화면에 뿌릴 목록. 이미 있는지, 이 PC에 버거운지 함께 준다."""
    out = []
    for e in CATALOG:
        out.append({
            "key": e.key, "role": e.role, "label": e.label, "size_mb": e.total_mb,
            "note": e.note, "installed": have(e, model_dir) or (also is not None and have(e, also)),   # also: 딸려 온 자리
            # 막지 않고 알려만 준다 — CPU로 돌리는 선택은 사용자 것이다.
            "heavy": bool(e.needs_vram and vram_mb and vram_mb < e.needs_vram),
        })
    return out


def _self_check() -> None:
    import tempfile
    import threading as th
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    # 목록은 규칙을 지켜야 한다.
    assert len({e.key for e in CATALOG}) == len(CATALOG), "키가 겹친다"
    for e in CATALOG:
        assert e.role in ("chat", "vision", "voice", "meaning")
        assert e.url.startswith("https://")
        assert "-of-" not in e.url, f"쪼개진 파일은 못 쓴다: {e.key}"
        if e.role == "vision":
            assert e.pair_url, f"비전인데 짝이 없다: {e.key}"

    # 저장 이름은 우리 규칙으로 바뀐다 — 짝을 이름으로 찾기 때문.
    with tempfile.TemporaryDirectory() as tmp:
        vl = find("qwen2.5-vl-3b")
        names = [p.name for _, p in target_paths(vl, tmp)]
        assert names == ["qwen2.5-vl-3b.gguf", "qwen2.5-vl-3b.mmproj.gguf"], names
        voice = [p.name for _, p in target_paths(find("ko-kss"), tmp)]
        assert voice == ["ko-kss.onnx", "ko-kss.onnx.json"], voice

    # --- 진짜 HTTP로 받아 본다 ---
    blob = b"x" * (3 << 20)  # 3MB

    class Serve(BaseHTTPRequestHandler):
        slow = False

        def log_message(self, *a):
            pass

        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Length", str(len(blob)))
            self.end_headers()
            for i in range(0, len(blob), 1 << 20):
                self.wfile.write(blob[i:i + (1 << 20)])
                if Serve.slow:
                    time.sleep(0.3)

    srv = ThreadingHTTPServer(("127.0.0.1", 0), Serve)
    th.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"

    with tempfile.TemporaryDirectory() as tmp:
        entry = Entry("test-vl", "vision", "검사용", f"{base}/a.gguf", 3,
                      pair_url=f"{base}/b.gguf", pair_size_mb=3)
        CATALOG_BACKUP = globals()["CATALOG"]
        globals()["CATALOG"] = CATALOG_BACKUP + (entry,)
        try:
            d = Downloader(tmp)
            assert d.start("test-vl")
            d._thread.join(30)
            assert d.progress.state == "done", (d.progress.state, d.progress.error)

            root = Path(tmp)
            assert (root / "test-vl.gguf").is_file() and (root / "test-vl.mmproj.gguf").is_file()
            # 끊긴 조각이 남으면 다음에 뭐가 뭔지 모른다.
            assert not list(root.glob("*.part")), "조각이 남았다"
            assert have(entry, tmp), "짝까지 있어야 있는 것이다"

            # 이미 있으면 다시 안 받는다.
            before = (root / "test-vl.gguf").stat().st_mtime_ns
            d2 = Downloader(tmp)
            d2.start("test-vl")
            d2._thread.join(30)
            assert (root / "test-vl.gguf").stat().st_mtime_ns == before

            # 멈출 수 있다. 멈추면 조각을 남기지 않는다.
            Serve.slow = True
            for f in root.glob("test-vl*"):
                f.unlink()
            d3 = Downloader(tmp)
            assert d3.start("test-vl")
            time.sleep(0.4)
            d3.cancel()
            d3._thread.join(30)
            assert d3.progress.state == "cancelled", d3.progress.state
            assert not list(root.glob("*.part")), "멈췄는데 조각이 남았다"
            assert not (root / "test-vl.gguf").exists(), "덜 받은 게 진짜 이름을 가졌다"
            Serve.slow = False

            # 없는 것은 못 받는다.
            assert not Downloader(tmp).start("없는키")

            # 앱이 강제 종료돼 남은 조각은 켤 때 치운다 — 실제로 겪은 상황이다.
            (root / "piper").mkdir(exist_ok=True)
            (root / "찌꺼기.gguf.part").write_bytes(b"x" * 100)
            (root / "piper" / "찌꺼기.onnx.part").write_bytes(b"x" * 100)
            fresh = Downloader(tmp)
            assert not list(root.rglob("*.part")), "켤 때 조각을 안 치웠다"
            assert fresh.sweep_parts() == 0  # 두 번 불러도 탈 없다

            # 버거운지 알려주되 막지는 않는다.
            rows = {r["key"]: r for r in listing(tmp, vram_mb=4096)}
            assert rows["qwen3-8b"]["heavy"] is True
            assert rows["qwen2.5-1.5b"]["heavy"] is False
            assert rows["test-vl"]["installed"] is False
        finally:
            globals()["CATALOG"] = CATALOG_BACKUP
            srv.shutdown()
            srv.server_close()

    # 뜻 검색 모델은 **낱말표까지 짝으로** 받아야 쓸 수 있다. 본체만 받으면 못 쓴다.
    big = find("e5-base")
    assert big is not None and big.role == "meaning"
    with tempfile.TemporaryDirectory() as tmp:
        where = [t for _, t in target_paths(big, tmp)]
        assert [w.name for w in where] == ["model.onnx", "tokenizer.json"], where
        # **딸려 온 것을 덮어쓰지 않는다** — 받은 것이 시원찮으면 폴더만 지우면 된다.
        assert all(w.parent.name == "e5-base" for w in where), where
        assert not have(big, tmp)
        for w in where:
            w.parent.mkdir(parents=True, exist_ok=True)
            w.write_bytes(b"x")
        assert have(big, tmp)

    print("model_store self-check 통과")


if __name__ == "__main__":
    _self_check()
