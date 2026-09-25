"""VC 자체 엔진 — 모델을 직접 올리고 내린다 (결정 36).

Ollama를 따로 깔고 관리하지 않는다. 사용자는 VC 하나만 설치한다.

**엔진을 직접 쥐어야만 되는 일 넷**(결정 27):

    상주 제어    자주 쓰는 모델을 올려둔 채로 둔다. 매번 로딩하면 첫 응답이 몇 초씩 늦다
    우선순위     전경 지시가 배경 분석을 앞지른다(결정 21이 큐까지 내려간다)
    맞물림 방지  GPU가 4GB면 두 모델이 동시에 안 올라간다. 먼저 내리고 올린다
    설치 일원화  모델 파일 위치·목록을 VC가 안다

바깥에서 보면 `backends.Backend`와 똑같이 생겼다. 그래서 `eb_config.json`에서
`kind`만 `local`로 바꾸면 나머지 코드는 한 줄도 안 바뀐다 — 클라우드 어댑터 3벌은
그대로 살아 있고(결정 3, BYO 키), 자체 엔진이 '자택 서버' 자리를 대신한다.

    {"backend": {"kind": "local", "model_dir": "../models"}}

모델은 GGUF 파일을 `models/`에 넣으면 이름으로 잡힌다. llama.cpp를 프로세스 안에서
쓰므로 서버도 포트도 없다.
"""

from __future__ import annotations

import paths

import gc
import os
import platform
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from backends import Backend, BackendError, _parts


def _add_cuda_dlls() -> None:
    """CUDA 런타임 DLL 경로를 알려준다.

    CUDA 휠의 llama.dll은 `cudart64_*.dll`·`cublas64_*.dll`을 필요로 하는데, CUDA
    Toolkit을 설치하지 않으면 시스템 PATH에 없다. pip로 받은 `nvidia-*` 패키지 안에
    같은 DLL이 들어 있으므로 그 폴더를 프로세스에만 등록한다.

    **사용자 PATH를 건드리지 않는다.** 설치형 앱이 시스템 환경변수를 고치면 지우기도
    어렵고 다른 프로그램에 영향이 간다. `add_dll_directory`는 이 프로세스에서만 산다.
    """
    if not hasattr(os, "add_dll_directory"):
        return  # 윈도우가 아니면 할 일이 없다
    import ctypes
    import site

    roots = [Path(p) / "nvidia" for p in site.getsitepackages()]
    roots.append(Path(site.getusersitepackages()) / "nvidia")

    folders = []
    for root in roots:
        if not root.is_dir():
            continue
        for folder in root.rglob("bin"):
            if any(folder.glob("*.dll")):
                folders.append(folder)
                try:
                    os.add_dll_directory(str(folder))
                except OSError:
                    pass

    # add_dll_directory만으로는 부족하다. llama_cpp는 winmode를 지정해 DLL을 열어서
    # 그 탐색 경로를 안 탄다 — 미리 이 프로세스에 올려두면 의존성이 거기서 해결된다.
    for folder in folders:
        # cudnn은 받아쓰기(CTranslate2)가 GPU로 돌 때 필요하다.
        for pattern in ("cudart64_*.dll", "cublas64_*.dll", "cublasLt64_*.dll",
                        "cudnn64_*.dll", "cudnn_*_infer64*.dll", "cudnn*.dll"):
            for dll in folder.glob(pattern):
                try:
                    ctypes.WinDLL(str(dll))
                except OSError:
                    pass

# 마지막으로 쓴 뒤 이만큼 놀면 내린다. VRAM을 붙들고 있으면 다른 모델이 못 올라온다.
IDLE_UNLOAD_SEC = 600

# 사양 등급. **개발용 PC 기준으로 값을 굳히면 안 된다** — 쓰는 사람마다 하드웨어가 다르고,
# 더 좋은 모델이 나오면 갈아 끼울 수 있어야 한다(결정 42).
TIERS = (
    # (등급, 최소 VRAM MB, 사람이 읽는 설명)
    ("high", 16000, "16GB+ — 큰 모델을 그대로 올린다"),
    ("mid", 8000, "8~16GB — 중간 모델, 비전 모델도 GPU에"),
    ("low", 4000, "4~8GB — 작은 모델, 비전은 CPU로 밀린다"),
    ("cpu", 0, "GPU 없음 — 전부 CPU. 작은 모델만 실용적"),
)


def detect_hardware() -> dict[str, Any]:
    """이 PC가 뭘 감당할 수 있는지 잰다. 추천값의 근거가 된다.

    GPU가 없거나 못 물어보면 조용히 cpu 등급으로 떨어진다 — 사양 판별이 실패했다고
    VC가 안 뜨면 안 된다.
    """
    name, vram = "", 0
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5, **paths.창안띄우기())
        if out.returncode == 0 and out.stdout.strip():
            first = out.stdout.strip().splitlines()[0]
            name, mb = (x.strip() for x in first.split(",", 1))
            vram = int(float(mb))
    except (OSError, ValueError, subprocess.SubprocessError):
        pass

    # ★★ **맥은 `nvidia-smi` 가 없다.** 그래서 늘 `cpu` 등급으로 떨어져 **모델이 GPU 를
    #   한 겹도 안 쓰고 돌았다**(`gpu_layers: 0`). 재서 잡았다 — 같은 물음이 직접 부르면
    #   11초, 서버를 거치면 60초였다(2026-09-21 · 맥 2호기 · qwen3-8b).
    #   애플 실리콘은 **메모리를 CPU 와 같이 쓴다**(통합 메모리) — llama.cpp 의 Metal 이
    #   그 메모리를 그대로 쓰므로, VRAM 대신 **시스템 메모리**로 등급을 매긴다.
    #   보수적으로 절반만 센다 — 나머지는 OS 와 앱이 쓴다.
    if not vram and platform.system() == "Darwin" and platform.machine() == "arm64":
        try:
            난것 = subprocess.run(["sysctl", "-n", "hw.memsize"],
                                capture_output=True, text=True, timeout=5, **paths.창안띄우기())
            바이트 = int((난것.stdout or "0").strip() or 0)
            if 바이트 > 0:
                vram = int(바이트 / (1024 * 1024) / 2)
                name = "Apple Silicon (통합 메모리)"
        except (OSError, ValueError, subprocess.SubprocessError):
            pass

    tier, note = 등급매기기(vram, bool(name) and platform.system() == "Darwin"
                          and platform.machine() == "arm64")
    return {"gpu": name, "vram_mb": vram, "tier": tier, "note": note}


def 등급매기기(vram_mb: int, 애플실리콘: bool) -> tuple[str, str]:
    """잰 메모리로 등급을 매긴다. **재는 쪽과 나누는 쪽을 갈라 뒀다** — 갈라야
    「메모리가 이만큼일 때 어떻게 되나」를 기계 없이 재 볼 수 있다.

    ★★ **애플 실리콘은 `cpu` 등급으로 안 내려간다.** 등급은 메모리로 매기는데,
    메모리가 적은 맥(8GB 맥북에어 같은 것)이 `cpu` 로 떨어져 **Metal 을 한 겹도
    안 쓰고 돌았다** — 2026-09-21 에 잡은 그 병이 낮은 등급에 그대로 남아 있었다.
    통합 메모리라 Metal 은 메모리가 적어도 쓸 수 있다. 적으면 **작은 모델**을
    쓰는 것이지 CPU 로 밀 일이 아니다.

    CI 의 맥 기계가 7GB 라 여기서 걸려 나왔다(2026-09-25, CI 를 얹은 첫판).
    쓰는 사람 중에 8GB 맥을 쓰는 사람이 그대로 밟을 자리였다.
    """
    tier, note = next((t, n) for t, floor, n in TIERS if vram_mb >= floor)
    if tier == "cpu" and 애플실리콘:
        return "low", "애플 실리콘 — 메모리가 적어 작은 모델만, 그래도 Metal 은 쓴다"
    return tier, note


# 등급별 권장값. **모델 이름을 코드에 박지 않는다** — 권장 크기와 조건만 적고,
# 실제로 무엇을 쓸지는 `models/`에 무엇이 있는지와 사용자의 선택이 정한다.
ADVICE = {
    "high": {"chat": "7~14B Q4", "vision": "7B급 비전 모델", "stt": "large-v3", "gpu_layers": -1},
    "mid": {"chat": "7B Q4", "vision": "3B급 비전 모델", "stt": "medium", "gpu_layers": -1},
    "low": {"chat": "1.5~3B Q4", "vision": "3B(CPU로 밀림)", "stt": "small", "gpu_layers": -1},
    "cpu": {"chat": "1.5B Q4", "vision": "권장 안 함(너무 느림)", "stt": "base", "gpu_layers": 0},
}

# 우선순위. 작을수록 먼저 간다. 전경 지시가 배경 분석에 밀리면 사용자가 기다린다.
FOREGROUND = 0
BACKGROUND = 10


@dataclass(order=True)
class _Job:
    priority: int
    seq: int
    run: Callable[[], Any] = field(compare=False)
    done: threading.Event = field(compare=False, default_factory=threading.Event)
    result: Any = field(compare=False, default=None)
    error: BaseException | None = field(compare=False, default=None)


class LocalEngine(Backend):
    """GGUF 모델을 이 프로세스 안에서 돌린다.

    한 번에 한 모델만 올린다. 4GB짜리 GPU에서 둘을 올리면 둘 다 못 쓴다 —
    쪼개 쓰는 것보다 바꿔 쓰는 게 낫다.
    """

    name = "local"

    # ★★ **채팅에 쓰려면 4096 은 좁다.** 근거 다섯 장에 앞말까지 실으면 바로 넘쳐서
    #   굽힌 앱이 「Requested tokens (4233) exceed context window of 4096」 으로
    #   막혔다(실기 · 2026-09-24). 넘치는 것 자체는 `query` 가 재서 막지만, 좁으면
    #   근거가 잘려 답이 얕아진다. qwen3-8b 은 훨씬 넓은 창을 견딘다.
    #   ★ 값이 걱정되면 설정 `backend.n_ctx` 로 되돌린다 — 창이 넓으면 KV 칸만큼
    #     메모리를 더 쓴다. 넓힌 쪽이 「채팅처럼 쓴다」에 맞는다고 보고 기본을 올렸다.
    기본칸 = 8192

    def __init__(self, model_dir: str | Path = "../models", n_ctx: int = 기본칸,
                 n_gpu_layers: int = -1, idle_unload_sec: int = IDLE_UNLOAD_SEC,
                 loader: Callable[..., Any] | None = None) -> None:
        self.model_dir = Path(model_dir)
        self.n_ctx = n_ctx
        self.n_gpu_layers = n_gpu_layers  # -1이면 GPU에 올릴 수 있는 만큼 다 올린다
        self.idle_unload_sec = idle_unload_sec
        self._loader = loader  # 검사에서 갈아 끼운다

        self._model: Any = None
        self._model_name = ""
        self._sees_images = False
        self._last_used = 0.0
        self._lock = threading.Lock()  # ponytail: 모델 하나뿐이라 전역 락으로 충분
        self._queue: list[_Job] = []
        self._seq = 0
        self._worker: threading.Thread | None = None

    # --- 모델 목록 -------------------------------------------------------

    def available(self) -> list[str]:
        """`models/`에 있는 GGUF. 확장자를 뗀 이름이 곧 모델 이름이다.

        `<이름>.mmproj.gguf`는 목록에 안 낸다 — 그건 모델이 아니라 비전 모델의 짝이다.
        """
        if not self.model_dir.is_dir():
            return []
        return sorted(p.stem for p in self.model_dir.glob("*.gguf")
                      if not p.stem.endswith(".mmproj"))

    def mmproj_of(self, model_path: Path) -> Path | None:
        """비전 모델의 짝. 이게 없으면 사진을 못 본다 — 글자 모델처럼 동작한다."""
        # with_suffix는 못 쓴다 — "llava-1.6-7b"의 ".6-7b"를 확장자로 보고 잘라먹는다.
        pair = model_path.parent / f"{model_path.stem}.mmproj.gguf"
        return pair if pair.is_file() else None

    def _path_of(self, model: str) -> Path:
        exact = self.model_dir / f"{model}.gguf"
        if exact.is_file():
            return exact
        # 이름을 다 안 쳐도 잡히게 한다. 파일명이 길고 규칙이 제각각이다.
        hits = [p for p in self.model_dir.glob("*.gguf") if model.lower() in p.stem.lower()]
        if len(hits) == 1:
            return hits[0]
        if not hits:
            raise BackendError(f"모델이 없다: {model} (가진 것: {', '.join(self.available()) or '없음'})")
        raise BackendError(f"이름이 여럿에 걸린다: {model} → {', '.join(p.stem for p in hits)}")

    # --- 상주 제어 -------------------------------------------------------

    def load(self, model: str) -> None:
        """필요한 모델을 올린다. 다른 게 올라와 있으면 먼저 내린다."""
        path = self._path_of(model)
        if self._model is not None and self._model_name == path.stem:
            self._last_used = time.monotonic()
            return

        self.unload()
        kwargs: dict[str, Any] = {}
        loader = self._loader
        if loader is None:
            _add_cuda_dlls()
            try:
                from llama_cpp import Llama
            except ImportError as e:
                raise BackendError(f"llama-cpp-python이 없다: {e}") from e
            loader = Llama

            mmproj = self.mmproj_of(path)
            if mmproj is not None:
                # 비전 모델. 짝 파일을 물려야 사진을 본다.
                from llama_cpp.llama_chat_format import MTMDChatHandler

                kwargs["chat_handler"] = MTMDChatHandler(clip_model_path=str(mmproj),
                                                         verbose=False)

        try:
            self._model = loader(model_path=str(path), n_ctx=self.n_ctx,
                                 n_gpu_layers=self.n_gpu_layers, verbose=False, **kwargs)
        except Exception as e:
            raise BackendError(f"모델을 못 올렸다: {e}") from e
        self._model_name = path.stem
        self._sees_images = self.mmproj_of(path) is not None
        self._last_used = time.monotonic()

    def unload(self) -> None:
        """VRAM을 놓는다. 참조만 지우면 GPU 메모리가 안 돌아온다 — gc까지 돌린다."""
        if self._model is None:
            return
        closer = getattr(self._model, "close", None)
        if callable(closer):
            closer()
        self._model = None
        self._model_name = ""
        self._sees_images = False
        gc.collect()

    def sweep(self) -> bool:
        """놀고 있으면 내린다. 안 내리면 다른 모델이 올라올 자리가 없다."""
        with self._lock:
            if self._model is None or self._queue:
                return False
            if time.monotonic() - self._last_used < self.idle_unload_sec:
                return False
            self.unload()
            return True

    @property
    def loaded(self) -> str:
        return self._model_name

    @property
    def sees_images(self) -> bool:
        """지금 올라온 모델이 사진을 보는가. 글자 모델에 사진을 주면 조용히 무시한다."""
        return self._sees_images

    # --- 우선순위 큐 -----------------------------------------------------

    def _pump(self) -> None:
        while True:
            with self._lock:
                if not self._queue:
                    self._worker = None
                    return
                self._queue.sort()
                job = self._queue.pop(0)
            try:
                job.result = job.run()
            except BaseException as e:  # noqa: BLE001 — 기다리는 쪽에 그대로 넘긴다
                job.error = e
            finally:
                job.done.set()

    def _submit(self, run: Callable[[], Any], priority: int) -> Any:
        job = _Job(priority=priority, seq=self._seq, run=run)
        with self._lock:
            self._seq += 1
            self._queue.append(job)
            if self._worker is None:
                self._worker = threading.Thread(target=self._pump, daemon=True)
                self._worker.start()
        job.done.wait()
        if job.error is not None:
            raise job.error
        return job.result

    # --- 추론 ------------------------------------------------------------

    def chat(self, messages: list[dict[str, Any]], model: str,
             priority: int = FOREGROUND, **곁: Any) -> str:
        """backends.Backend와 같은 얼굴. 부르는 쪽은 로컬인지 클라우드인지 모른다.

        `곁`은 llama.cpp 로 그대로 넘긴다(`temperature`·`max_tokens`…). 얼굴을 안
        바꾸려고 뒤에 붙였다 — 안 주면 지금까지와 똑같이 돈다.

        **문지기는 `temperature=0` 으로 부른다.** 같은 조각을 두 번 재는데 답이
        갈리면 20년치 기록에서 무엇이 왜 들어왔는지 아무도 못 되짚는다.
        """

        def work() -> str:
            self.load(model)
            out = self._model.create_chat_completion(messages=_to_llama(messages), **곁)
            self._last_used = time.monotonic()
            try:
                return out["choices"][0]["message"]["content"] or ""
            except (KeyError, IndexError, TypeError) as e:
                raise BackendError(f"응답 형식이 다르다: {out}") from e

        return self._submit(work, priority)


def _to_llama(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """내부 메시지 형식 → llama.cpp 형식.

    llama.cpp는 OpenAI 규격을 따라 이미지도 `image_url`로 받는다. 다만 비전 모델과
    mmproj가 같이 있어야 실제로 본다 — 없으면 모델이 이미지를 무시한다.
    """
    out = []
    for m in messages:
        parts = _parts(m["content"])
        if len(parts) == 1 and parts[0]["type"] == "text":
            out.append({"role": m["role"], "content": parts[0]["text"]})
            continue
        content = []
        for p in parts:
            if p["type"] == "text":
                content.append({"type": "text", "text": p["text"]})
            else:
                content.append({"type": "image_url", "image_url": {
                    "url": f"data:{p['media_type']};base64,{p['data']}"}})
        out.append({"role": m["role"], "content": content})
    return out


def _self_check() -> None:
    import tempfile

    tmp = tempfile.TemporaryDirectory()
    root = Path(tmp.name)
    for name in ("qwen2.5-0.5b-instruct-q4", "llava-1.6-7b-q4"):
        (root / f"{name}.gguf").write_bytes(b"fake")

    loaded: list[str] = []
    closed: list[str] = []

    class FakeLlama:
        def __init__(self, model_path, n_ctx, n_gpu_layers, verbose):
            self.name = Path(model_path).stem
            self.n_ctx = n_ctx
            loaded.append(self.name)

        def create_chat_completion(self, messages):
            return {"choices": [{"message": {"content": f"{self.name}:{messages[-1]['content']}"}}]}

        def close(self):
            closed.append(self.name)

    eng = LocalEngine(root, loader=FakeLlama)

    # 목록은 파일에서 나온다.
    assert eng.available() == ["llava-1.6-7b-q4", "qwen2.5-0.5b-instruct-q4"]

    # 이름을 다 안 쳐도 잡힌다.
    assert eng._path_of("qwen2.5-0.5b").stem == "qwen2.5-0.5b-instruct-q4"
    for bad, why in [("없는모델", "모델이 없다"), ("q4", "여럿에 걸린다")]:
        try:
            eng._path_of(bad)
        except BackendError as e:
            assert why in str(e), e
        else:
            raise AssertionError(f"{bad}가 통과했다")

    # backends.Backend와 같은 얼굴이다.
    assert eng.chat([{"role": "user", "content": "안녕"}], "qwen2.5-0.5b") \
        == "qwen2.5-0.5b-instruct-q4:안녕"
    assert eng.loaded == "qwen2.5-0.5b-instruct-q4"

    # 같은 모델을 또 부르면 다시 안 올린다 — 상주가 이 엔진의 이유다.
    eng.chat([{"role": "user", "content": "또"}], "qwen2.5-0.5b")
    assert loaded.count("qwen2.5-0.5b-instruct-q4") == 1, "같은 모델을 두 번 올렸다"

    # 다른 모델을 부르면 먼저 내리고 올린다. 4GB에 둘은 안 들어간다.
    eng.chat([{"role": "user", "content": "사진"}], "llava")
    assert closed == ["qwen2.5-0.5b-instruct-q4"], closed
    assert eng.loaded == "llava-1.6-7b-q4"

    # 놀면 내린다. 대신 방금 쓴 건 안 내린다.
    assert eng.sweep() is False
    eng._last_used -= IDLE_UNLOAD_SEC + 1
    assert eng.sweep() is True and eng.loaded == ""

    # 전경이 배경을 앞지른다.
    order: list[str] = []
    gate = threading.Event()

    class SlowLlama(FakeLlama):
        def create_chat_completion(self, messages):
            gate.wait(2)  # 첫 작업이 붙잡고 있는 동안 뒤에 줄이 선다
            order.append(messages[-1]["content"])
            return {"choices": [{"message": {"content": "ok"}}]}

    q = LocalEngine(root, loader=SlowLlama)
    threads = [
        threading.Thread(target=q.chat, args=([{"role": "user", "content": "첫번째"}], "qwen")),
    ]
    threads[0].start()
    time.sleep(0.15)  # 첫 작업이 큐를 잡을 때까지
    for text, prio in (("배경", BACKGROUND), ("전경", FOREGROUND)):
        t = threading.Thread(target=q.chat,
                             args=([{"role": "user", "content": text}], "qwen"),
                             kwargs={"priority": prio})
        t.start()
        threads.append(t)
        time.sleep(0.05)
    gate.set()
    for t in threads:
        t.join(5)
    assert order == ["첫번째", "전경", "배경"], f"우선순위가 안 먹었다: {order}"

    # 실패는 부른 쪽으로 그대로 올라간다 — 조용히 삼키면 승격 판단을 못 한다.
    class BrokenLlama(FakeLlama):
        def create_chat_completion(self, messages):
            raise RuntimeError("out of memory")

    broken = LocalEngine(root, loader=BrokenLlama)
    try:
        broken.chat([{"role": "user", "content": "x"}], "qwen")
    except RuntimeError as e:
        assert "out of memory" in str(e)
    else:
        raise AssertionError("터진 걸 삼켰다")

    # 모델이 없으면 그 사실을 말한다.
    empty = LocalEngine(root / "없는폴더", loader=FakeLlama)
    assert empty.available() == []
    try:
        empty.chat([{"role": "user", "content": "x"}], "아무거나")
    except BackendError as e:
        assert "모델이 없다" in str(e)

    # 비전 모델의 짝(mmproj)은 목록에 안 나오고, 짝이 있으면 사진을 본다고 표시한다.
    (root / "llava-1.6-7b-q4.mmproj.gguf").write_bytes(b"fake")
    # ★ 기본 창이 채팅에 쓸 만큼 넓은가 — 좁히면 근거가 잘려 답이 얕아진다
    assert LocalEngine(root, loader=FakeLlama).n_ctx >= 8192
    assert LocalEngine(root, n_ctx=4096, loader=FakeLlama).n_ctx == 4096   # 되돌릴 수 있다

    eng2 = LocalEngine(root, loader=FakeLlama)
    assert "llava-1.6-7b-q4.mmproj" not in eng2.available(), eng2.available()
    assert eng2.mmproj_of(root / "llava-1.6-7b-q4.gguf") is not None
    assert eng2.mmproj_of(root / "qwen2.5-0.5b-instruct-q4.gguf") is None

    # 사양을 재서 등급을 매긴다. GPU가 없어도 죽지 않고 cpu 등급으로 떨어진다.
    hw = detect_hardware()
    assert hw["tier"] in ADVICE and hw["vram_mb"] >= 0, hw
    assert hw["note"], "등급 설명이 비었다"
    # 등급마다 권장이 다르다 — 개발용 PC 기준으로 굳으면 안 된다.
    assert ADVICE["cpu"]["gpu_layers"] == 0 and ADVICE["high"]["gpu_layers"] == -1
    # ★★ **맥에서 GPU 를 한 겹도 안 쓰고 돌던 것.** `nvidia-smi` 만 보느라 애플 실리콘이
    #   늘 `cpu` 등급이었다 — 같은 물음이 직접 부르면 11초, 서버를 거치면 60초였다
    #   (2026-09-21 재서 잡았다). 통합 메모리라 시스템 메모리로 등급을 매긴다.
    import platform as _플랫폼

    # ★★ **메모리가 적은 맥도 GPU 를 쓴다.** 기계 없이 여기서 잰다 — 이 맥이
    #   64GB 라 위 검사만으로는 낮은 등급 길을 한 번도 안 지난다. 실제로 CI 의
    #   7GB 맥에서 `cpu` 로 떨어져 나왔다.
    for _잰것 in (0, 1000, 3584, 3999):
        _등급, _말 = 등급매기기(_잰것, 애플실리콘=True)
        assert ADVICE[_등급]["gpu_layers"] == -1, f"{_잰것}MB 애플 실리콘이 CPU 로 밀렸다: {_등급}"
        assert "Metal" in _말, _말
    # 애플 실리콘이 아니면 그대로 cpu 로 떨어져야 한다 — 없는 GPU 를 쓰겠다고 하면 안 된다
    assert 등급매기기(0, 애플실리콘=False)[0] == "cpu"
    assert 등급매기기(20000, 애플실리콘=False)[0] == "high"

    난것 = detect_hardware()
    if _플랫폼.system() == "Darwin" and _플랫폼.machine() == "arm64":
        assert 난것["vram_mb"] > 0, f"애플 실리콘을 못 알아본다: {난것}"
        assert ADVICE[난것["tier"]]["gpu_layers"] == -1, \
            f"맥에서 GPU 를 안 쓴다: {난것['tier']}"
    # 어느 기계든 등급은 넷 중 하나이고 권장값이 있다
    assert 난것["tier"] in ADVICE, 난것
    assert ADVICE["high"]["chat"] != ADVICE["cpu"]["chat"]

    # 이미지는 OpenAI 규격 그대로 나간다.
    conv = _to_llama([{"role": "user", "content": [
        {"type": "text", "text": "이거 뭐야"},
        {"type": "image", "media_type": "image/png", "data": "QUJD"},
    ]}])
    assert conv[0]["content"][1]["image_url"]["url"] == "data:image/png;base64,QUJD"
    # 글자만 있으면 문자열 그대로 — 굳이 파트로 감싸지 않는다.
    assert _to_llama([{"role": "user", "content": "안녕"}])[0]["content"] == "안녕"

    print("engine self-check 통과")


if __name__ == "__main__":
    _self_check()
