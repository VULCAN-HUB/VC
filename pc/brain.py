"""온디바이스 1단 모델 — 어느 모듈을 부를지 고른다(결정 11).

라우팅은 **생성이 아니라 분류**다. "이거 뭐야"가 제품 검색인지 번역인지 고르는 일에
문장 생성 모델은 과하다. 작고 빠른 유사도 판정이면 되고, 그래야 폰에서 항상 켜 둘 수 있다.

3단 구조에서 이 파일은 2단이다:

    1단 규칙 매칭   오케스트레이터가 한다. 트리거가 하나만 걸리면 그대로 실행
    2단 이 파일     여러 개 걸리거나 하나도 안 걸릴 때 유사도로 고른다
    3단 되묻기      확신이 없으면 **고르지 않는다**. None을 돌려주면 VC가 되묻는다

확신 기준을 둘 둔다(결정 11: 확신 없이 실행하지 않는다):

    최저점   제일 가까운 것도 이만큼 안 되면 아무것도 안 고른다
    격차     1등과 2등이 붙어 있으면 안 고른다. 반반이면 찍는 것이지 아는 게 아니다

모델은 갈아 끼울 수 있다. `NgramBrain`은 의존성이 0이라 어디서든 돌고, 임베딩 모델이
생기면 `EmbedBrain`에 끼워 넣으면 된다 — 폰에서는 ONNX Runtime, PC에서는 무엇이든.

**쓸수록 좋아진다.** 모듈이 어떤 말에 반응할지는 스킬 선언에 쌓이고(결정 30), 되묻던
표현이 승인되면 예시로 들어와 다음부터 안 되묻는다. 학습 루프가 여기로 이어진다.
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Iterable, Protocol

# 유사도 문턱. 낮추면 엉뚱한 모듈이 돌고, 높이면 자꾸 되묻는다.
# 되묻는 쪽이 덜 나쁘다 — 잘못 고르면 비용이 나가고 사용자가 되돌려야 한다.
MIN_SCORE = 0.34
MIN_MARGIN = 0.07

# 임베딩은 절대점수가 0.84~0.96 좁은 띠에 몰린다. 절대값으로는 못 자르고 격차로 자른다.
# 실측: 맞는 판정 0.031~0.073 / 틀린 판정 0.004~0.016 → 0.025에서 갈린다.
EMBED_MIN_SCORE = 0.78
EMBED_MIN_MARGIN = 0.025

_STRIP = re.compile(r"[\s!?.,~…\-_/\\()\[\]{}'\"]+")


def normalize(text: str) -> str:
    """한글은 자모 분리 형태로 들어오는 경우가 있어 NFC로 모은다. 띄어쓰기는 버린다.

    '이거뭐야'와 '이거 뭐야'를 다른 말로 보면 사용자는 매번 되묻는 VC를 만난다.
    """
    return _STRIP.sub("", unicodedata.normalize("NFC", text)).lower()


def grams(text: str, sizes: Iterable[int] = (2, 3)) -> Counter:
    """문자 n-gram. 형태소 분석기 없이 조사·어미 변화를 견딘다.

    ponytail: '출근 준비해줘'와 '출근 준비'가 겹치게 하는 데 이거면 충분하다. 형태소
    분석기는 사전·용량을 달고 오는데 폰에서 그 값을 치를 만큼 정확해지지 않는다.
    """
    s = normalize(text)
    bag: Counter = Counter()
    for n in sizes:
        if len(s) < n:
            bag[s] += 1  # 짧은 말도 버리지 않는다
            continue
        for i in range(len(s) - n + 1):
            bag[s[i : i + n]] += 1
    return bag


def cosine(a: Counter, b: Counter) -> float:
    if not a or not b:
        return 0.0
    common = set(a) & set(b)
    dot = sum(a[k] * b[k] for k in common)
    if not dot:
        return 0.0
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    return dot / (na * nb)


def decide(scores: dict[str, float], min_score: float, min_margin: float) -> str | None:
    """점수에서 하나를 고르거나, 확신이 없으면 아무것도 안 고른다(결정 11)."""
    if not scores:
        return None
    ranked = sorted(scores.items(), key=lambda kv: -kv[1])
    best, top = ranked[0]
    second = ranked[1][1] if len(ranked) > 1 else 0.0

    if top < min_score:
        return None  # 아는 말이 아니다
    if top - second < min_margin:
        return None  # 반반이면 찍는 것이지 아는 게 아니다
    return best


class Embedder(Protocol):
    """문장을 벡터로. 폰에서는 ONNX Runtime, PC에서는 무엇이든 끼울 수 있다."""

    def __call__(self, texts: list[str]) -> list[list[float]]: ...


class NgramBrain:
    """의존성 0짜리 1단 모델. 모델 파일이 없어도 VC는 굴러가야 한다(결정 25).

    각 모듈이 반응할 말들을 모아 두고, 들어온 지시와 제일 가까운 모듈을 고른다.
    """

    def __init__(self, min_score: float = MIN_SCORE, min_margin: float = MIN_MARGIN) -> None:
        self.min_score = min_score
        self.min_margin = min_margin
        self.phrases: dict[str, list[Counter]] = {}
        self.last: dict[str, float] = {}  # 직전 판정 점수. 계측·설명에 쓴다

    def learn(self, module: str, phrases: Iterable[str]) -> None:
        """이 모듈이 어떤 말에 반응하는지 알려준다. 여러 번 불러도 쌓인다."""
        bag = self.phrases.setdefault(module, [])
        for phrase in phrases:
            if phrase and phrase.strip():
                bag.append(grams(phrase))

    def forget(self) -> None:
        self.phrases.clear()
        getattr(self, "vectors", {}).clear()

    def relearn(self, modules: Iterable, skills: Iterable = ()) -> None:
        """모듈·스킬이 바뀌면 처음부터 다시 배운다.

        덧붙이기만 하면 지워진 스킬의 말이 남아 없는 모듈을 계속 가리킨다.
        """
        self.forget()
        for mod in modules:
            self.learn(mod.name, [mod.name, *getattr(mod, "triggers", [])])
        for skill in skills:
            self.learn(skill.name, [*getattr(skill, "triggers", []),
                                    *getattr(skill, "examples", [])])

    def score(self, text: str, choices: list[str]) -> dict[str, float]:
        """모듈별 점수. 이름 자체도 후보에 넣는다 — '번역'이라고 말하면 번역이다."""
        target = grams(text)
        out = {}
        for name in choices:
            examples = self.phrases.get(name) or []
            best = max((cosine(target, e) for e in examples), default=0.0)
            out[name] = max(best, cosine(target, grams(name)))
        return out

    def classify(self, text: str, choices: list[str]) -> str | None:
        if not choices:
            return None
        self.last = self.score(text, choices)
        return decide(self.last, self.min_score, self.min_margin)


class EmbedBrain(NgramBrain):
    """임베딩 모델이 생기면 여기에 끼운다. 판정 규칙은 n-gram 쪽과 똑같이 쓴다.

    폰: ONNX Runtime으로 소형 다국어 임베딩 모델. PC: 무엇이든.
    모델을 못 불러오면 조용히 n-gram으로 내려간다 — 라우팅이 멈추면 VC가 벙어리가 된다.
    """

    def __init__(self, embed: Embedder, embed_min: float = EMBED_MIN_SCORE,
                 embed_margin: float = EMBED_MIN_MARGIN, **kw) -> None:
        super().__init__(**kw)
        self.embed = embed
        self.embed_min = embed_min
        self.embed_margin = embed_margin
        self.vectors: dict[str, list[list[float]]] = {}

    def learn(self, module: str, phrases: Iterable[str]) -> None:
        items = [p for p in phrases if p and p.strip()]
        if not items:
            return
        super().learn(module, items)  # 모델이 죽어도 돌아갈 자리를 남겨 둔다
        try:
            self.vectors.setdefault(module, []).extend(self.embed(items))
        except Exception:
            self.vectors.pop(module, None)

    def score(self, text: str, choices: list[str]) -> dict[str, float]:
        """임베딩 점수. 모델이 없거나 터지면 n-gram 점수로 내려간다."""
        if not self.vectors:
            return super().score(text, choices)
        try:
            (query,) = self.embed([text])
        except Exception:
            return super().score(text, choices)

        out = {}
        for name in choices:
            vecs = self.vectors.get(name) or []
            out[name] = max((_dot_cos(query, v) for v in vecs), default=0.0)
        return out

    def classify(self, text: str, choices: list[str]) -> str | None:
        """글자로 먼저 보고, 안 갈리면 뜻으로 본다.

        n-gram은 '이거뭐야' 같은 표기 흔들림에 강하고 틀릴 때가 드물다. 임베딩은
        '출근할 때 뭐 챙기지'처럼 글자가 안 겹치는 같은 뜻을 잡는다. 둘의 점수 범위가
        달라서 문턱을 섞을 수 없으므로 순서대로 태운다.
        """
        if not choices:
            return None

        lexical = super().score(text, choices)
        picked = decide(lexical, self.min_score, self.min_margin)
        if picked:
            self.last = lexical
            return picked

        self.last = self.score(text, choices)
        return decide(self.last, self.embed_min, self.embed_margin)


def _dot_cos(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def pin_runtime(*_a, **_kw) -> bool:
    """`paths.pin_runtime` 을 그대로 부른다 — 붙드는 일은 한 곳에만 둔다."""
    import paths

    return paths.pin_runtime()


def onnx_embedder(model_dir: str | Path = "../models",
                  max_tokens: int = 128) -> Embedder | None:
    """ONNX Runtime 임베딩. 폰에서도 같은 파일이 그대로 돈다(ONNX Runtime Mobile).

    파일이나 런타임이 없으면 None을 돌려준다 — 모델이 없다고 VC가 멈추면 안 된다.

    `max_tokens`는 한 번에 읽는 길이다. 기본 128은 **지시 한 줄**을 재는 값이고,
    기록 본문을 재려면 512쯤 준다(한글 1.88자/토큰이라 128토큰이면 241자에서 잘린다 —
    1,200자 조각을 넣어 놓고 앞 241자만 재고 있던 적이 있다).
    """
    d = Path(model_dir)
    if not (d / "model.onnx").exists() or not (d / "tokenizer.json").exists():
        return None
    try:
        import numpy as np
        import onnxruntime as ort
        from tokenizers import Tokenizer
    except ImportError:
        return None

    sess = ort.InferenceSession(str(d / "model.onnx"), providers=["CPUExecutionProvider"])
    tok = Tokenizer.from_file(str(d / "tokenizer.json"))
    tok.enable_padding()
    tok.enable_truncation(max_length=max_tokens)
    needs_type_ids = any(i.name == "token_type_ids" for i in sess.get_inputs())

    def embed(texts: list[str], prefix: str = "query: ") -> list[list[float]]:
        # e5 계열은 접두사를 붙여 학습됐다. 빼면 점수가 눈에 띄게 떨어진다.
        # 찾는 말은 `query: `, 찾히는 글은 `passage: ` 로 서로 다르게 붙인다.
        encoded = tok.encode_batch([prefix + t for t in texts])
        ids = np.array([e.ids for e in encoded], dtype=np.int64)
        mask = np.array([e.attention_mask for e in encoded], dtype=np.int64)
        feed = {"input_ids": ids, "attention_mask": mask}
        if needs_type_ids:
            feed["token_type_ids"] = np.zeros_like(ids)

        hidden = sess.run(None, feed)[0]
        # 평균 풀링. 패딩 자리를 빼고 나눠야 짧은 문장이 0쪽으로 끌려가지 않는다.
        m = mask[..., None].astype(np.float32)
        pooled = (hidden * m).sum(1) / np.maximum(m.sum(1), 1e-9)
        pooled /= np.maximum(np.linalg.norm(pooled, axis=1, keepdims=True), 1e-9)
        return pooled.tolist()

    return embed


def build(modules: Iterable, skills: Iterable = (), embed: Embedder | None = None) -> NgramBrain:
    """모듈 선언과 승인된 스킬에서 1단 모델을 만든다.

    모듈의 트리거가 씨앗이고, 스킬에 쌓인 예시가 그 위에 얹힌다 — 되묻던 표현이
    승인될 때마다 여기로 들어와 다음부터 안 되묻는다.
    """
    if embed is None:
        embed = onnx_embedder()  # 있으면 쓰고, 없으면 n-gram으로 돈다
    brain = EmbedBrain(embed) if embed is not None else NgramBrain()
    brain.relearn(modules, skills)
    return brain


def _self_check() -> None:
    from dataclasses import dataclass, field

    @dataclass
    class FakeModule:
        name: str
        triggers: list[str] = field(default_factory=list)

    mods = [
        FakeModule("제품 검색", ["이거 뭐야", "얼마", "시세"]),
        FakeModule("번역", ["번역", "뭐라고 써", "무슨 뜻"]),
        FakeModule("출근 준비", ["출근 준비", "회사 갈 준비"]),
    ]
    brain = build(mods)
    names = [m.name for m in mods]

    # 띄어쓰기·어미가 달라도 같은 말로 본다.
    assert brain.classify("이거뭐야?", names) == "제품 검색"
    assert brain.classify("이거 뭐야 대체", names) == "제품 검색"
    assert brain.classify("출근 준비해줘", names) == "출근 준비"
    assert brain.classify("이거 무슨 뜻이야", names) == "번역"

    # 모듈 이름을 그대로 말해도 통한다.
    assert brain.classify("번역", names) == "번역"

    # 모르는 말에는 손대지 않는다 — 되묻는 쪽이 덜 나쁘다.
    assert brain.classify("냉장고에 뭐 있지", names) is None
    assert brain.classify("", names) is None

    # 후보가 붙어 있으면 안 고른다. 반반이면 찍는 것이지 아는 게 아니다.
    tie = build([FakeModule("가", ["출근 준비"]), FakeModule("나", ["출근 준비"])])
    assert tie.classify("출근 준비", ["가", "나"]) is None, "붙었는데 하나를 골랐다"

    # 예시가 쌓이면 되묻던 말을 알아듣는다 — 학습 루프가 여기로 이어진다.
    assert brain.classify("그거 좀 해줘", names) is None
    brain.learn("출근 준비", ["그거 좀 해줘"])
    assert brain.classify("그거 좀 해줘", names) == "출근 준비"

    # 승인된 스킬의 예시가 build에서 실려 온다.
    @dataclass
    class FakeSkill:
        name: str
        triggers: list[str] = field(default_factory=list)
        examples: list[str] = field(default_factory=list)

    grown = NgramBrain()
    grown.relearn(mods, [FakeSkill("번역", examples=["이거 읽어줘"])])
    assert grown.classify("이거 읽어줘", names) == "번역"

    # 임베딩을 끼우면 그쪽으로 판정한다.
    table = {"출근 준비": [1.0, 0.0], "이불 정리": [0.0, 1.0], "아침에 할 것": [0.96, 0.28]}

    def fake_embed(texts: list[str]) -> list[list[float]]:
        return [table.get(t, [0.0, 0.0]) for t in texts]

    em = EmbedBrain(fake_embed)
    em.learn("출근 준비", ["출근 준비"])
    em.learn("정리", ["이불 정리"])
    assert em.classify("아침에 할 것", ["출근 준비", "정리"]) == "출근 준비"

    # 다시 배우면 사라진 스킬의 말은 같이 사라진다.
    grown.relearn(mods)
    assert grown.classify("이거 읽어줘", names) is None, "지워진 스킬의 말이 남았다"

    # 모델이 터져도 VC는 안 멈춘다 — n-gram으로 내려간다.
    def broken(texts: list[str]) -> list[list[float]]:
        raise RuntimeError("모델 없음")

    fallback = EmbedBrain(broken)
    fallback.learn("번역", ["번역", "무슨 뜻"])
    assert fallback.classify("무슨 뜻이야", ["번역"]) == "번역"

    # --- 진짜 ONNX 모델이 있으면 뜻까지 잡는지 확인한다 ---
    embed = onnx_embedder()
    if embed is None:
        print("brain self-check 통과 (임베딩 모델 없음 — n-gram만 확인)")
        return

    real = build(mods, embed=embed)
    # 글자가 하나도 안 겹치는데 같은 뜻 — n-gram은 절대 못 잡는다.
    assert NgramBrain().classify("출근할 때 뭐 챙기지", names) is None
    assert real.classify("출근할 때 뭐 챙기지", names) == "출근 준비"
    assert real.classify("소리 좀 키워봐", names + ["볼륨"]) != "제품 검색"
    # 표기가 흔들려도 글자 쪽에서 먼저 잡는다.
    assert real.classify("이거뭐야", names) == "제품 검색"
    # 아무 데도 안 맞으면 여전히 안 고른다.
    assert real.classify("냉장고에 뭐 있지", names) is None

    print("brain self-check 통과 (ONNX 임베딩 포함)")


if __name__ == "__main__":
    _self_check()
