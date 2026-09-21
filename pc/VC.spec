# -*- mode: python ; coding: utf-8 -*-
"""VC 설치본 명세.

**폴더 통째(onedir)로 만든다.** 예전 배포에서 재본 결과가 그렇게 말한다:
onefile은 실행할 때 자기를 임시폴더에 풀어내는데, 그게 백신 오탐의 대표 트리거고
기동도 느리다(3.95초 → 1.36초, 2.9배). 행사 당일 백신에 막히면 되돌릴 방법이 없다.

**UPX를 쓰지 않는다.** 압축 실행파일은 오탐을 부른다. 버전 메타는 채운다.

**모델은 안 넣는다** — 뜻 검색과 목소리만 넣는다. 대화(1.1GB)·비전(2.6GB)·받아쓰기는
앱 안에서 받는다(`model_store.py`). CUDA 뒷단(`ggml-cuda.dll`)은 946MB인데 NVIDIA가
없는 사람에게는 순손실이라 뺀다 — 필요하면 나중에 따로 얹는다.
"""
import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

# **현재 폴더가 아니라 이 명세 파일 자리를 기준으로 잡는다.**
# `os.getcwd()` 로 잡았더니, 정션(`C:cbuild`)에서 구울 때 모델을 `C:\models` 에서
# 찾다 죽었다. 손으로 돌릴 때는 cwd 가 실제 경로로 풀려 우연히 맞아서 안 보였다.
# `SPECPATH` 는 PyInstaller 가 넣어 준다.
HERE = Path(SPECPATH).resolve()
MODELS = HERE.parent / "models"
# 상자에 담을 대화 엔진은 **CPU 판**이다. 아래 「엔진 담기」 설명 참고.
ENGINE = HERE.parent / "빌드전용"

# 같이 넣을 자료. (원본, 상자 안 자리)
#
# 뜻 검색 모델은 **꼭 넣는다.** 없으면 의미 검색이 꺼진 채로 시작하는데, 사용자는
# 그게 꺼진 줄도 모른다.
# **딸려 보내는 것은 늘 작은 쪽(e5-small)이다.** 큰 것(e5-base 279MB)은 앱 안에서
# 받는다 — 상자를 가볍게 두기로 한 결정이고, 받으면 `paths.meaning_dir()` 이 알아서
# 그쪽을 먼저 쓴다.
bundle = [
    (str(MODELS / "model.onnx"), "models"),
    (str(MODELS / "tokenizer.json"), "models"),
]
if (MODELS / "piper").exists():
    bundle.append((str(MODELS / "piper"), "models/piper"))

# 안 넣는 것. 넣으면 상자가 몇 GB가 되고, 정작 없어도 기록 프로그램으로는 다 돌아간다.
DROP = [
    "torch", "torchvision", "torchaudio",
    "matplotlib", "scipy", "pandas", "IPython", "notebook",
    "PyQt5.QtWebEngineCore", "PyQt5.QtWebEngineWidgets", "PyQt5.QtWebEngine",
    "PyQt5.Qt3DCore", "PyQt5.Qt3DRender", "PyQt5.QtBluetooth",
    "PyQt5.QtDesigner", "PyQt5.QtHelp", "PyQt5.QtLocation",
    "PyQt5.QtMultimediaWidgets", "PyQt5.QtNfc", "PyQt5.QtQuick3D",
    "PyQt5.QtRemoteObjects", "PyQt5.QtSensors", "PyQt5.QtSerialPort",
    "PyQt5.QtSql", "PyQt5.QtTest", "PyQt5.QtWebSockets", "PyQt5.QtXmlPatterns",
    "tkinter", "unittest", "pydoc_data",
]

# onnxruntime 은 **통째로 풀어서** 담는다.
#
# 파이썬 파일이 묶음(PYZ) 안에 들어가면 `__file__` 이 실제로 없는 자리를 가리켜서,
# 제 DLL 자리를 잡는 코드가 헛돈다 — 그러면 불러오다
# "DLL 초기화 루틴을 실행할 수 없습니다"로 죽는다. 파일로 풀어 두면 제 자리를 찾는다.
ort_datas, ort_bins, ort_hidden = collect_all("onnxruntime")

# ── 엔진 담기 ──────────────────────────────────────────────────────────
#
# 흡수의 비싼 문지기가 쓰는 대화 엔진이다. **개발 자리에 깔린 것을 담으면 안 된다.**
#
# 여기 깔린 것은 CUDA 판이고, 그 판의 `ggml.dll` 이 `ggml-cuda.dll` 을 **정적으로**
# 문다(있으면 쓰고 없으면 넘어가는 식이 아니다). 하나씩 열어 보고 알았다:
#
#     ggml-base.dll 열림 · ggml-cpu.dll 열림 · ggml.dll **안 열림**
#
# 그래서 CUDA 를 빼면 사슬이 끊기고, 안 빼면 `ggml-cuda.dll` 902MB 에 그것이 무는
# cuBLAS 736MB 까지 딸려 온다. 처음엔 이걸 「엔진은 못 담는다」로 잘라 두고
# `DROP` 에 넣어 뒀는데, **그러면 설치본에서 문지기가 한 번도 안 돈다** —
# 구운 것으로 돌려 보니 1058 조각이 1초 만에 전부 통과했고 셈만 보면 멀쩡했다.
#
# CPU 판은 같은 사슬이 CUDA 를 안 문다. DLL 다 합쳐 **5.7MB** 다. 그래서 CPU 판만
# `빌드전용/` 에 따로 받아 그것을 담는다. **개발 자리에 깔린 CUDA 판은 안 건드린다**
# — 여기서 시험 돌릴 때의 속도가 그대로 남는다.
#
#     python -m pip install --target 빌드전용 --only-binary :all: --no-deps
#         --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu
#         llama-cpp-python
#
#   (한 줄로 이어서 친다. PyPI 에는 미리 구운 휠이 없어 `--extra-index-url` 이 있어야
#    받아진다 — 없으면 「No matching distribution found」 로 끝난다.)
MAC = sys.platform == "darwin"
# 맥: CUDA 가 없어 그 사슬 문제가 없다. pip 로 깐 llama-cpp-python(Metal)을 그대로 담는다 — build_mac.sh
if MAC and not (ENGINE / "llama_cpp").is_dir():
    ENGINE = Path(__import__("site").getsitepackages()[0])
if not (ENGINE / "llama_cpp").is_dir():
    raise SystemExit(chr(10).join([
        f"[VC.spec] 대화 엔진이 없다: {ENGINE / 'llama_cpp'}",
        "  위 주석의 pip 한 줄로 CPU 판을 받아라. 그거 없이 구우면 흡수의 비싼",
        "  문지기가 설치본에서 한 번도 안 돈다(그런데 셈은 「다 통과」로 보인다)."]))
sys.path.insert(0, str(ENGINE))
llama_datas, llama_bins, llama_hidden = collect_all("llama_cpp")
# 링크용 `.lib` 는 도는 데 필요 없다. CUDA 판을 잘못 집었는지도 여기서 걸린다.
llama_datas = [d for d in llama_datas if not d[0].lower().endswith(".lib")]
llama_bins = [b for b in llama_bins if not b[0].lower().endswith(".lib")]
큰것 = [d[0] for d in llama_datas + llama_bins if "cuda" in d[0].lower()]
if 큰것:
    raise SystemExit(f"[VC.spec] CUDA 판을 집었다: {큰것[:3]}")
print(f"[VC.spec] 대화 엔진 {'Metal' if MAC else 'CPU'} 판 담음 — 자료 {len(llama_datas)}개 "
      f"· 이진 {len(llama_bins)}개")


a = Analysis(
    ["eb.py"],
    pathex=[str(HERE)],
    binaries=ort_bins + llama_bins,
    datas=bundle + ort_datas + llama_datas,
    # 이름으로만 불러 쓰는 것들. 안 적으면 빌드는 되고 **실행할 때** 없다고 죽는다.
    hiddenimports=[
        "onnxruntime", "tokenizers", "faster_whisper", "ctranslate2",
        "sounddevice", "segno", "piper",
        # 우리 모듈이지만 eb.py 가 늦게 부르는 것들. 안 적으면 빌드는 되고
        # **실행할 때** 없다고 죽는다.
        "paths", "report", "ui", "server", "phone_app", "phone_relay", "voice", "brain", "notes", "panels", "theme",
        "graph3d", "logo", "store", "talklog", "orchestrator", "modules",
        "skills", "engine", "backends", "remote", "phone_relay",
        "product_search", "models_config", "model_store", "eb_protocol",
        "ingest", "gate", "settings", "keystore", "connectors", "selflearn", "google_auth",
        # 창고의 네 가지 일과 2단계(헤르메스). 늦게 불러 쓰므로 여기 없으면 구운 판에서 죽는다.
        "wiki", "wikilog", "synth", "audit", "query", "consolidate",
        "hermes", "codefiles", "vibe", "skillgen", "agentcli",
        # 아래 열하나는 **전부터 빠져 있던 것들**이다(검사를 넣고서야 드러났다).
        "ai_fill", "demo", "facets", "mic_tune", "mirror", "orders", "piles",
        "plugins", "tailnet", "transcribe", "vault",
    ] + ort_hidden + llama_hidden,
    hookspath=[],
    runtime_hooks=[],
    excludes=DROP,
    noarchive=False,
    optimize=0,
)
# **PyQt5 가 딸고 오는 낡은 MSVC 런타임을 뺀다.**
#
# PyQt5 는 불러올 때 제 `Qt5\bin` 을 DLL 찾는 자리 **앞에** 끼워 넣는다. 그 안에 든
# msvcp140/vcruntime140 은 2019년 판(14.26)인데, onnxruntime 1.27 은 더 새 판을
# 요구한다. 그래서 낡은 쪽을 물고 `DllMain` 이 실패한다:
#
#   ImportError: DLL load failed while importing onnxruntime_pybind11_state:
#   DLL 초기화 루틴을 실행할 수 없습니다.
#
# 이 하나로 **개발 중(Qt 불러온 뒤)과 설치본 양쪽에서 똑같이** 뜻 검색이 죽었다.
# `import PyQt5` 한 줄이면 충분하고 QApplication 은 필요도 없다.
#
# MSVC 런타임은 위로 호환된다 — 새것 하나(상자 뿌리에 이미 있다)면 Qt 도 onnxruntime 도
# 같이 쓴다. 지우는 게 아니라 **중복을 없애는 것**이다.
OLD_RUNTIME = ("msvcp140", "vcruntime140", "concrt140")
kept = []
for name, src, kind in a.binaries:
    low = name.lower().replace("\\", "/")
    if "qt5/bin/" in low and any(low.rsplit("/", 1)[-1].startswith(x) for x in OLD_RUNTIME):
        continue
    kept.append((name, src, kind))
dropped = len(a.binaries) - len(kept)
print(f"[VC.spec] PyQt5 의 낡은 MSVC 런타임 {dropped}개 뺌")
a.binaries = kept

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="VC",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,          # 압축은 오탐을 부른다
    console=False,      # 창 프로그램이다. 검은 콘솔이 같이 뜨면 안 된다
    # 맥은 .ico·버전 파일을 안 쓴다 — 아이콘은 BUNDLE 이 .png 를 .icns 로 바꿔 담는다(Pillow)
    icon=None if MAC else str(HERE / "vc.ico"),
    version=None if MAC else str(HERE / "version.txt"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="VC",
)

if MAC:
    sys.path.insert(0, str(HERE))
    import paths as _paths

    app = BUNDLE(
        coll,
        name="VC.app",
        icon=str(HERE / "vc_mac.png") if (HERE / "vc_mac.png").is_file() else None,
        bundle_identifier="com.unknown8563.vc",
        version=_paths.VERSION,
        info_plist={
            "CFBundleDisplayName": "VC",
            "CFBundleShortVersionString": _paths.VERSION,
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": "12.0",
            # 말로 시키기(받아쓰기). 문구가 없으면 맥이 마이크를 묻지도 않고 막는다
            "NSMicrophoneUsageDescription": "VC 에게 말로 시키려고 마이크를 쓴다",
            # 폰 앱·같은 공유기 기기가 붙는 서버(8765)
            "NSLocalNetworkUsageDescription": "같은 와이파이의 폰 앱이 VC 창고에 붙는다",
        },
    )
