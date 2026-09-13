"""백엔드 어댑터 3벌 (결정 3).

- OpenAICompatible: 자택 서버(Ollama·LM Studio·vLLM)와 OpenAI 호환 제공자 전부
- Anthropic: 클로드
- Gemini: 제미나이

내부 메시지 형식은 하나로 고정하고 각 어댑터가 자기 규격으로 번역한다.
새 제공자를 붙일 때 건드릴 곳이 이 파일 하나가 되도록 한다.

    messages = [{"role": "user", "content": "안녕"}]
    messages = [{"role": "user", "content": [
        {"type": "text", "text": "이거 뭐야"},
        {"type": "image", "media_type": "image/jpeg", "data": "<base64>"},
    ]}]

의존성은 표준 라이브러리만 쓴다. 요청 한 번에 JSON 한 덩어리를 주고받는 게 전부라
HTTP 클라이언트 라이브러리를 더할 이유가 없다.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

TIMEOUT_SEC = 120


class BackendError(RuntimeError):
    """어댑터가 답을 못 받았다. 호출한 쪽이 상위 단계로 승격할지 정한다(결정 24)."""


def _post(url: str, headers: dict[str, str], payload: dict[str, Any]) -> dict[str, Any]:
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", **headers},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SEC) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        # 본문에 원인이 들어 있다. 그대로 올려야 학습 로그의 failure_point가 쓸모 있어진다.
        body = e.read().decode("utf-8", "replace")[:500]
        raise BackendError(f"HTTP {e.code}: {body}") from e
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise BackendError(str(e)) from e


def _parts(content: Any) -> list[dict[str, Any]]:
    """content를 항상 파트 리스트로 정규화한다."""
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    return content


class Backend:
    name = "backend"

    def chat(self, messages: list[dict[str, Any]], model: str) -> str:
        raise NotImplementedError


class OpenAICompatible(Backend):
    """자택 서버와 OpenAI 호환 제공자. PC 자신도 폰에게는 이 모양으로 보인다(결정 25)."""

    name = "openai_compatible"

    def __init__(self, base_url: str, api_key: str = "") -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key

    def chat(self, messages: list[dict[str, Any]], model: str) -> str:
        out = []
        for m in messages:
            parts = []
            for p in _parts(m["content"]):
                if p["type"] == "text":
                    parts.append({"type": "text", "text": p["text"]})
                else:
                    url = f"data:{p['media_type']};base64,{p['data']}"
                    parts.append({"type": "image_url", "image_url": {"url": url}})
            out.append({"role": m["role"], "content": parts})

        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        data = _post(
            f"{self.base_url}/chat/completions",
            headers,
            {"model": model, "messages": out},
        )
        return data["choices"][0]["message"]["content"]


class Anthropic(Backend):
    name = "anthropic"
    endpoint = "https://api.anthropic.com/v1/messages"
    version = "2023-06-01"

    def __init__(self, api_key: str, max_tokens: int = 2048) -> None:
        self.api_key = api_key
        self.max_tokens = max_tokens

    def chat(self, messages: list[dict[str, Any]], model: str) -> str:
        system, out = None, []
        for m in messages:
            if m["role"] == "system":
                # 클로드는 system을 메시지 목록 밖에 둔다.
                system = _parts(m["content"])[0]["text"]
                continue
            parts = []
            for p in _parts(m["content"]):
                if p["type"] == "text":
                    parts.append({"type": "text", "text": p["text"]})
                else:
                    parts.append(
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": p["media_type"],
                                "data": p["data"],
                            },
                        }
                    )
            out.append({"role": m["role"], "content": parts})

        payload: dict[str, Any] = {
            "model": model,
            "max_tokens": self.max_tokens,
            "messages": out,
        }
        if system:
            payload["system"] = system

        data = _post(
            self.endpoint,
            {"x-api-key": self.api_key, "anthropic-version": self.version},
            payload,
        )
        return "".join(b["text"] for b in data["content"] if b["type"] == "text")


class Gemini(Backend):
    name = "gemini"
    base = "https://generativelanguage.googleapis.com/v1beta/models"

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key

    def chat(self, messages: list[dict[str, Any]], model: str) -> str:
        system, contents = None, []
        for m in messages:
            if m["role"] == "system":
                system = {"parts": [{"text": _parts(m["content"])[0]["text"]}]}
                continue
            parts = []
            for p in _parts(m["content"]):
                if p["type"] == "text":
                    parts.append({"text": p["text"]})
                else:
                    parts.append(
                        {
                            "inline_data": {
                                "mime_type": p["media_type"],
                                "data": p["data"],
                            }
                        }
                    )
            # 제미나이는 assistant를 model이라 부른다.
            role = "model" if m["role"] == "assistant" else "user"
            contents.append({"role": role, "parts": parts})

        payload: dict[str, Any] = {"contents": contents}
        if system:
            payload["system_instruction"] = system

        data = _post(
            f"{self.base}/{model}:generateContent",
            {"x-goog-api-key": self.api_key},
            payload,
        )
        cand = data["candidates"][0]
        return "".join(p.get("text", "") for p in cand["content"]["parts"])


def build(cfg: dict[str, Any]) -> Backend:
    """설정에서 어댑터를 만든다. PC 프로그램의 엔진 선택 UI가 이 dict를 쓴다."""
    kind = cfg.get("kind")
    if kind == "local":
        # VC 자체 엔진(결정 36). 여기서 import하는 이유는 engine이 backends를 쓰기
        # 때문이다 — 위에서 import하면 순환이 된다.
        from engine import LocalEngine

        return LocalEngine(**{k: v for k, v in cfg.items() if k != "kind"})
    import keystore

    # 키는 설정의 평문이 아니라 운영체제 보관소에 산다(오너 결정 1). 평문이 남아 있으면 그것을 쓴다.
    if kind == "openai_compatible":
        return OpenAICompatible(cfg["base_url"], keystore.키꺼내기(cfg))
    if kind == "anthropic":
        return Anthropic(keystore.키꺼내기(cfg))
    if kind == "gemini":
        return Gemini(keystore.키꺼내기(cfg))
    raise ValueError(f"모르는 백엔드 종류: {kind}")


def _self_check() -> None:
    """네트워크 없이 페이로드 번역만 확인한다. 규격을 잘못 옮기는 게 여기서 나올 실수다."""
    sent: dict[str, Any] = {}

    def fake_post(url, headers, payload):
        sent.update(url=url, headers=headers, payload=payload)
        return fake_post.reply

    global _post
    real_post, _post = _post, fake_post
    try:
        msgs = [
            {"role": "system", "content": "너는 VC다"},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "이거 뭐야"},
                    {"type": "image", "media_type": "image/jpeg", "data": "QUJD"},
                ],
            },
        ]

        fake_post.reply = {"choices": [{"message": {"content": "펜"}}]}
        assert OpenAICompatible("http://pc:11434/v1", "k").chat(msgs, "m") == "펜"
        assert sent["url"].endswith("/v1/chat/completions")
        assert sent["headers"]["Authorization"] == "Bearer k"
        img = sent["payload"]["messages"][1]["content"][1]
        assert img["image_url"]["url"].startswith("data:image/jpeg;base64,")

        fake_post.reply = {"content": [{"type": "text", "text": "펜"}]}
        assert Anthropic("k").chat(msgs, "m") == "펜"
        assert sent["payload"]["system"] == "너는 VC다"
        assert len(sent["payload"]["messages"]) == 1, "system이 메시지 목록에 남아 있다"
        assert sent["payload"]["messages"][0]["content"][1]["source"]["data"] == "QUJD"
        assert sent["headers"]["anthropic-version"] == Anthropic.version

        fake_post.reply = {"candidates": [{"content": {"parts": [{"text": "펜"}]}}]}
        assert Gemini("k").chat(msgs, "m") == "펜"
        assert sent["payload"]["system_instruction"]["parts"][0]["text"] == "너는 VC다"
        assert sent["payload"]["contents"][0]["parts"][1]["inline_data"]["data"] == "QUJD"
        assert sent["headers"]["x-goog-api-key"] == "k"

        from engine import LocalEngine

        for cfg, cls in (
            ({"kind": "local", "model_dir": "../models"}, LocalEngine),
            ({"kind": "openai_compatible", "base_url": "u"}, OpenAICompatible),
            ({"kind": "anthropic", "api_key": "k"}, Anthropic),
            ({"kind": "gemini", "api_key": "k"}, Gemini),
        ):
            assert isinstance(build(cfg), cls)
        # ★ 설정에 키가 없으면 운영체제 보관소에서 꺼낸다(오너 결정 1). 진짜 보관소는 안 건드린다.
        import keystore

        옛get, 옛있나 = keystore.get, keystore.available
        keystore.get = lambda 이름: "보관소키" if 이름 == "backend:gemini" else None
        keystore.available = lambda: True
        try:
            assert build({"kind": "gemini", "api_key_in": "keystore"}).api_key == "보관소키", \
                "보관소로 옮긴 키를 어댑터가 못 받는다"
            assert build({"kind": "gemini", "api_key": "평문"}).api_key == "평문"
        finally:
            keystore.get, keystore.available = 옛get, 옛있나
        try:
            build({"kind": "없는것"})
        except ValueError:
            pass
        else:
            raise AssertionError("모르는 백엔드가 통과했다")
    finally:
        _post = real_post

    print("backends self-check 통과")


if __name__ == "__main__":
    _self_check()
