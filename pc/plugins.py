"""확장 플러그인 통로 (오너 결정 23 · 편의 기능 31번 · 옵시디언 플러그인).

한 확장 = **앱 자리**의 폴더 하나(`~/Library/Application Support/VC/plugins/<이름>/`):

    plugin.json   {"name": "보기수", "version": "1", "note": "무엇을 하는지", "needs": []}
    main.py       def register(vc): ...

`vc` 로 여는 문은 **좁게** 둔다(결정 23):

    vc.log("말")                      자국(`vc-기록.log`)에 한 줄
    vc.command("이름", 함수)          명령 — 사람이 부른다
    vc.on_saved(함수)                 글이 저장된 뒤 (제목)
    vc.module("이름", ["방아쇠"], 함수)  지시에 반응하는 부품 — 함수(글) → 답할 말
    vc.read(제목) · vc.append(제목, 글)  창고 읽기·덧붙이기

★ **기본은 꺼짐.** 설정에서 켠 것만 싣는다 — 폴더에 넣는 것만으로는 코드가 안 돈다.
★ **하나가 터져도 VC 는 산다.** 싣기·부르기의 예외를 잡아 자국에 남기고 그 확장만 끈다.
★ 폰 앱은 코드 확장을 안 받는다(스토어 규칙) — 폰에 필요한 것은 컴퓨터 쪽 확장이 문을 연다.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import paths

FOLDER = "plugins"
SPEC = "plugin.json"
ENTRY = "main.py"
CONFIG_KEY = "확장"          # 설정: {"확장": {"보기수": true}}


@dataclass
class Module:
    """확장이 낸 부품. 확장은 VC 를 **아무것도 import 하지 않는다** — 여기 모아 두면
    서버가 `orchestrator.ModuleSpec` 으로 옮긴다(확장이 VC 속을 만지지 못하게)."""

    name: str
    triggers: list[str]
    run: Callable[[str], str]


@dataclass
class Info:
    name: str
    folder: Path
    version: str = ""
    note: str = ""
    needs: list[str] = field(default_factory=list)
    enabled: bool = False
    error: str = ""


def root(where: str | Path | None = None) -> Path:
    return Path(where) if where else paths.기계자리(FOLDER)


def enabled_names(cfg: dict | None = None) -> set[str]:
    cfg = cfg if cfg is not None else paths.load_config()
    got = cfg.get(CONFIG_KEY) or {}
    return {k for k, v in got.items() if v is True} if isinstance(got, dict) else set()


def find(where: str | Path | None = None, cfg: dict | None = None) -> list[Info]:
    """확장 폴더를 훑는다. 깨진 `plugin.json` 은 **버리지 않고 까닭을 달아** 보여 준다."""
    base = root(where)
    on = enabled_names(cfg)
    out: list[Info] = []
    if not base.is_dir():
        return out
    for folder in sorted(p for p in base.iterdir() if p.is_dir()):
        spec, entry = folder / SPEC, folder / ENTRY
        if not spec.is_file() and not entry.is_file():
            continue
        info = Info(name=folder.name, folder=folder, enabled=folder.name in on)
        try:
            j = json.loads(spec.read_text(encoding="utf-8")) if spec.is_file() else {}
            if not isinstance(j, dict):
                raise ValueError("plugin.json 이 표가 아니다")
            info.name = str(j.get("name") or folder.name)
            info.version = str(j.get("version") or "")
            info.note = str(j.get("note") or "")
            needs = j.get("needs") or []
            info.needs = [str(x) for x in needs] if isinstance(needs, list) else []
            info.enabled = info.name in on or folder.name in on
        except (OSError, ValueError) as e:
            info.error = f"{SPEC} 를 못 읽었다: {type(e).__name__}"
        if not entry.is_file():
            info.error = info.error or f"{ENTRY} 가 없다"
        out.append(info)
    return out


def enable(name: str, on: bool) -> bool:
    """설정에 켜고 끈 것을 남긴다. 다시 켤 때 그대로 뜬다."""
    cfg = paths.load_config()
    got = dict(cfg.get(CONFIG_KEY) or {})
    got[name] = bool(on)
    paths.save_config({**cfg, CONFIG_KEY: got})
    return bool(on)


class Api:
    """확장에 건네는 좁은 문. 여기 없는 것은 확장이 못 한다(결정 23)."""

    def __init__(self, name: str, store: Any = None, log: Callable[[str], None] | None = None) -> None:
        self.name = name
        self._store = store
        self._log = log
        self.commands: dict[str, Callable[..., Any]] = {}
        self.saved: list[Callable[[str], Any]] = []
        self.modules: list[Module] = []

    # --- 확장이 부르는 것 ---
    def log(self, 말: str) -> None:
        if self._log:
            self._log(f"[확장 {self.name}] {말}")

    def command(self, 이름: str, 함수: Callable[..., Any]) -> None:
        self.commands[str(이름)] = 함수

    def on_saved(self, 함수: Callable[[str], Any]) -> None:
        self.saved.append(함수)

    def module(self, 이름: str, 방아쇠: list[str], 함수: Callable[[str], str]) -> None:
        self.modules.append(Module(str(이름), [str(t) for t in (방아쇠 or [])], 함수))

    def read(self, 제목: str):
        return self._store.read(제목) if self._store else None

    def append(self, 제목: str, 글: str):
        return self._store.append(제목, 글) if self._store else None


@dataclass
class Loaded:
    infos: list[Info]
    apis: dict[str, Api] = field(default_factory=dict)

    @property
    def modules(self) -> list[tuple[str, Module]]:
        return [(확장, m) for 확장, api in self.apis.items() for m in api.modules]

    @property
    def commands(self) -> dict[str, tuple[str, Callable[..., Any]]]:
        return {이름: (확장, 함수) for 확장, api in self.apis.items() for 이름, 함수 in api.commands.items()}

    def fire_saved(self, title: str, log: Callable[[str], None] | None = None) -> None:
        """글이 저장됐다고 알린다. **한 확장이 터져도 다음 확장은 돈다.**"""
        for 이름, api in list(self.apis.items()):
            for 함수 in list(api.saved):
                try:
                    함수(title)
                except Exception as e:
                    if log:
                        log(f"[확장 {이름}] 저장 알림에서 터졌다 — {type(e).__name__}: {e}")

    def run(self, command: str, *args, log: Callable[[str], None] | None = None) -> Any:
        got = self.commands.get(command)
        if not got:
            return None
        이름, 함수 = got
        try:
            return 함수(*args)
        except Exception as e:
            if log:
                log(f"[확장 {이름}] 명령 「{command}」 에서 터졌다 — {type(e).__name__}: {e}")
            return None


def load(where: str | Path | None = None, store: Any = None, cfg: dict | None = None,
         log: Callable[[str], None] | None = None) -> Loaded:
    """**켠 것만** 싣는다. 못 실은 것은 `Info.error` 에 까닭이 남고 나머지는 그대로 돈다."""
    infos = find(where, cfg)
    out = Loaded(infos=infos)
    for info in infos:
        if not info.enabled or info.error:
            continue
        api = Api(info.name, store, log)
        try:
            spec = importlib.util.spec_from_file_location(f"vc_확장_{info.folder.name}", info.folder / ENTRY)
            if spec is None or spec.loader is None:
                raise ImportError("못 읽었다")
            mod = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = mod
            spec.loader.exec_module(mod)
            register = getattr(mod, "register", None)
            if not callable(register):
                raise AttributeError("register(vc) 가 없다")
            register(api)
        except Exception as e:
            # ★ 확장이 터져도 VC 는 산다 — 그 확장만 안 싣고 까닭을 남긴다
            info.error = f"{type(e).__name__}: {e}"
            if log:
                log(f"[확장 {info.name}] 못 실었다 — {info.error}")
                log(f"[확장 {info.name}] {traceback.format_exc(limit=3).splitlines()[-1]}")
            continue
        out.apis[info.name] = api
        if log:
            log(f"[확장 {info.name}] 실었다 — 명령 {len(api.commands)} · 저장 알림 {len(api.saved)} · 부품 {len(api.modules)}")
    return out


SAMPLE = {
    SPEC: ('{\n'
           '  "name": "글자수",\n'
           '  "version": "1",\n'
           '  "note": "글 하나의 글자 수를 세어 자국에 적는다 — 새 확장을 만들 때 이 폴더를 복사한다"\n'
           '}\n'),
    ENTRY: '''"""보기 확장 예제 — 이 폴더를 복사해 새 확장을 만든다(오너 결정 23).

`register(vc)` 하나만 있으면 된다. `vc` 로 할 수 있는 것은 VC 의 `pc/plugins.py` 머리글에 적혀 있고,
거기 없는 것은 확장이 못 한다 — 확장이 창고를 망가뜨리거나 바깥으로 글을 보낼 길은 열려 있지 않다.
"""


def register(vc):
    def 글자수(제목=""):
        글 = vc.read(제목)
        if 글 is None:
            vc.log(f"「{제목}」 이 없다")
            return None
        수 = len(글.body)
        vc.log(f"「{제목}」 은 {수}자")
        return 수

    vc.command("글자수", 글자수)
    vc.on_saved(lambda 제목: vc.log(f"저장됨 — {제목}"))
''',
}


def write_sample(where: str | Path | None = None, name: str = "글자수") -> Path:
    """예제 확장을 깔아 둔다(기본 꺼짐) — 사람이 복사해 새 확장을 만든다."""
    folder = root(where) / name
    folder.mkdir(parents=True, exist_ok=True)
    for 이름, 글 in SAMPLE.items():
        자리 = folder / 이름
        if not 자리.exists():
            자리.write_text(글, encoding="utf-8")
    return folder


def _self_check() -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp) / "plugins"
        # 예제는 깔리지만 **꺼져 있다**
        write_sample(base)
        infos = find(base, cfg={})
        assert [i.name for i in infos] == ["글자수"], [i.name for i in infos]
        assert not infos[0].enabled and not infos[0].error, infos[0]
        말들: list[str] = []
        빈 = load(base, store=None, cfg={}, log=말들.append)
        assert not 빈.apis and not 말들, "꺼져 있는데 실었다"

        class 가짜글:
            body = "가나다"

        class 가짜창고:
            def read(self, 제목):
                return None if 제목 == "없음" else 가짜글()

            def append(self, 제목, 글):
                말들.append(f"덧붙임 {제목}")
                return 제목

        켬 = {"확장": {"글자수": True}}
        실림 = load(base, store=가짜창고(), cfg=켬, log=말들.append)
        assert "글자수" in 실림.apis and "글자수" in 실림.commands, 실림.commands
        assert 실림.run("글자수", "어떤 글", log=말들.append) == 3
        assert 실림.run("글자수", "없음", log=말들.append) is None
        실림.fire_saved("어떤 글", log=말들.append)
        assert any("저장됨 — 어떤 글" in x for x in 말들), 말들
        assert 실림.run("없는 명령") is None

        # 부품 — 확장은 VC 를 import 하지 않고 이름·방아쇠·함수만 준다
        부품 = base / "부품낸것"
        부품.mkdir()
        (부품 / SPEC).write_text('{"name": "부품낸것"}', encoding="utf-8")
        (부품 / ENTRY).write_text(
            "def register(vc):\n    vc.module('날씨', ['날씨'], lambda 글: '맑다')\n", encoding="utf-8")
        실림부 = load(base, store=None, cfg={"확장": {"부품낸것": True}}, log=말들.append)
        assert [(확장, m.name, m.triggers) for 확장, m in 실림부.modules] == [("부품낸것", "날씨", ["날씨"])], 실림부.modules
        assert 실림부.modules[0][1].run("오늘 날씨") == "맑다"

        # 터지는 확장 — VC 는 산다
        나쁜 = base / "나쁜것"
        나쁜.mkdir()
        (나쁜 / SPEC).write_text('{"name": "나쁜것"}', encoding="utf-8")
        (나쁜 / ENTRY).write_text("def register(vc):\n    raise RuntimeError('일부러')\n", encoding="utf-8")
        켬2 = {"확장": {"글자수": True, "나쁜것": True}}
        실림2 = load(base, store=가짜창고(), cfg=켬2, log=말들.append)
        assert "글자수" in 실림2.apis and "나쁜것" not in 실림2.apis, 실림2.apis
        나쁜정보 = next(i for i in 실림2.infos if i.name == "나쁜것")
        assert "RuntimeError" in 나쁜정보.error, 나쁜정보.error

        # 저장 알림에서 터져도 다음 확장은 돈다
        터짐 = base / "저장터짐"
        터짐.mkdir()
        (터짐 / SPEC).write_text('{"name": "저장터짐"}', encoding="utf-8")
        (터짐 / ENTRY).write_text(
            "def register(vc):\n    vc.on_saved(lambda 제목: (_ for _ in ()).throw(ValueError('터짐')))\n",
            encoding="utf-8")
        실림3 = load(base, store=가짜창고(), cfg={"확장": {"글자수": True, "저장터짐": True}}, log=말들.append)
        말들.clear()
        실림3.fire_saved("또 다른 글", log=말들.append)
        assert any("저장됨 — 또 다른 글" in x for x in 말들), "한 확장이 터져 다음 확장이 멈췄다"
        assert any("저장 알림에서 터졌다" in x for x in 말들), 말들

        # register 가 없으면 까닭이 남는다
        빈것 = base / "빈것"
        빈것.mkdir()
        (빈것 / SPEC).write_text('{"name": "빈것"}', encoding="utf-8")
        (빈것 / ENTRY).write_text("x = 1\n", encoding="utf-8")
        실림4 = load(base, store=None, cfg={"확장": {"빈것": True}}, log=말들.append)
        assert "register(vc) 가 없다" in next(i for i in 실림4.infos if i.name == "빈것").error

        # plugin.json 이 깨져도 목록에는 뜬다(까닭과 함께)
        깨짐 = base / "깨짐"
        깨짐.mkdir()
        (깨짐 / SPEC).write_text("{깨진", encoding="utf-8")
        (깨짐 / ENTRY).write_text("def register(vc):\n    pass\n", encoding="utf-8")
        정보 = next(i for i in find(base, cfg={}) if i.folder.name == "깨짐")
        assert "plugin.json" in 정보.error, 정보.error
    print("plugins self-check 통과")


if __name__ == "__main__":
    if "--check" in sys.argv:
        _self_check()
