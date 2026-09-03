"""제품 검색 — 첫 진짜 부품(결정 26).

시선이 머문 물건을 식별한다. 사진 한 장을 받아 무엇인지 답한다.

단계별로 하는 일이 다르다(결정 5·24):

    phone   온디바이스 비전. 아직 없다 → 바로 올려보낸다
    pc      자택 서버의 비전 모델. 여기서 대부분 끝나야 한다(비용 0)
    api     클라우드. 자택이 못 하거나 확신이 모자랄 때만

**확신이 모자라면 위로 올린다.** 애매한 답을 그대로 내놓으면 사용자는 그게 틀렸다는
걸 모른다. 올려도 여전히 모자라면 모자란 채로 말한다 — "펜이야"와 "펜 같은데"는
사용자가 다르게 받아들인다.

시세는 아직 안 붙였다. 가격 조회는 제공자마다 규격도 약관도 달라서 따로 정해야 한다.
`price_lookup`을 넘기면 그 자리에 끼워진다.
"""

from __future__ import annotations

import base64
import json
import re
from typing import Any, Callable

from orchestrator import Instruction, ModuleFailed, ModuleSpec

# 이 아래로는 위 단계에 물어본다. 올려도 안 되면 그때는 이 값 아래여도 답한다.
MIN_CONFIDENCE = 0.55

# 채울 자리에 한국어 예시값을 써두면 작은 모델이 그걸 그대로 베껴 온다("물건 이름").
# 값은 보여주지 말고 **무엇을 넣어야 하는지만** 설명한다. 예시는 딴 물건으로 하나만 둔다.
PROMPT = """사진을 보고 가장 중심에 있는 물건 하나를 식별해라.
JSON 한 줄만 출력한다. 설명도 코드펜스도 붙이지 마라.

키와 값:
- name: 그 물건을 한국어로 뭐라 부르는지
- brand: 사진에서 브랜드가 보이면 그 이름, 안 보이면 ""
- category: 어떤 종류인지 한 단어
- confidence: 네가 얼마나 확신하는지 0.0~1.0 사이 숫자
- note: 눈에 띄는 특징 한 줄

예시(다른 사진에 대한 답):
{"name":"운동화","brand":"","category":"신발","confidence":0.83,"note":"흰색 로우탑"}

사진에 없는 것을 지어내지 마라. 모르겠으면 confidence를 낮춰라.
**물건이 안 보이면 name을 빈 문자열로 두고 confidence를 0으로 해라.**
빈 화면이든 풍경이든, 없는 물건을 만들어 내지 마라."""

MAGIC = {
    b"\xff\xd8\xff": "image/jpeg",
    b"\x89PNG\r\n\x1a\n": "image/png",
    b"RIFF": "image/webp",
    b"GIF8": "image/gif",
}


def media_type(data: bytes) -> str:
    """확장자가 아니라 내용으로 판별한다. 폰이 보내는 건 이름이 없을 때가 많다."""
    for magic, mime in MAGIC.items():
        if data.startswith(magic):
            return mime
    raise ModuleFailed("image_format", "이미지 형식을 모르겠다")


def parse_json(text: str) -> dict[str, Any]:
    """모델이 뭘 덧붙여도 JSON만 건져낸다.

    코드펜스로 감싸거나 앞뒤에 말을 붙이는 건 프롬프트로 못 막는다. 파싱에서 견딘다.
    """
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ModuleFailed("parse", f"JSON이 아니다: {text[:80]}")
    try:
        return json.loads(match.group())
    except json.JSONDecodeError as e:
        raise ModuleFailed("parse", f"JSON이 깨졌다: {e}") from e


# 모델이 "물건 없음"을 적어 보내는 말들. 이걸 물건 이름으로 받으면 VC가 헛소리를 한다.
NOTHING = {"", "없음", "없다", "없어", "모름", "모르겠음", "unknown", "none", "n/a", "null"}


def normalize_name(name: Any) -> str:
    return str(name or "").strip().strip(".。").lower()


def identify(backend: Any, model: str, image: bytes, hint: str = "") -> dict[str, Any]:
    """사진 한 장을 모델에 보내 식별 결과를 받는다."""
    if not image:
        raise ModuleFailed("no_image", "사진이 없다")

    parts: list[dict[str, Any]] = [{"type": "text", "text": PROMPT}]
    if hint:
        parts.append({"type": "text", "text": f"사용자가 한 말: {hint}"})
    parts.append({
        "type": "image",
        "media_type": media_type(image),
        "data": base64.b64encode(image).decode(),
    })

    try:
        raw = backend.chat([{"role": "user", "content": parts}], model)
    except Exception as e:
        # 백엔드가 죽었는지 모델이 못 했는지 구분해서 남겨야 분석이 쓸모 있다.
        raise ModuleFailed("vision_model", str(e)) from e

    # 글자 모델은 사진을 조용히 무시하고 그럴듯한 답을 지어낸다. 그게 제일 나쁜 실패다.
    if getattr(backend, "sees_images", True) is False:
        raise ModuleFailed("not_vision_model",
                           f"{model}은 사진을 못 본다. 비전 모델(mmproj 짝)이 필요하다")

    out = parse_json(raw)
    # 빈 문자열로 두라고 했는데도 "없음"이라고 적어 보낸다. 그것도 없는 것이다 —
    # 안 걸러내면 "없음이야"라고 말하는 VC가 된다.
    if normalize_name(out.get("name")) in NOTHING:
        raise ModuleFailed("nothing_seen", "사진에서 물건을 못 찾았다")
    try:
        out["confidence"] = float(out.get("confidence", 0))
    except (TypeError, ValueError):
        out["confidence"] = 0.0
    return out


def describe(found: dict[str, Any], price: str = "") -> str:
    """사람에게 하는 말. 확신이 모자라면 모자란 티를 낸다."""
    name = found["name"]
    brand = (found.get("brand") or "").strip()
    label = f"{brand} {name}".strip()

    if found["confidence"] >= MIN_CONFIDENCE:
        line = f"{label}이야."
    else:
        line = f"{label}인 것 같은데 확실하진 않아."

    if found.get("note"):
        line += f" {found['note']}"
    if price:
        line += f" {price}"
    return line


def build(backend: Any = None, model: str = "",
          price_lookup: Callable[[dict], str] | None = None) -> ModuleSpec:
    """제품 검색 모듈 하나. 백엔드가 없으면 단계마다 실패하고 그대로 보고된다."""

    def run(inst: Instruction) -> str:
        if inst.tier == "phone":
            # 온디바이스 비전이 없다. 폰 앱이 나오면 ML Kit 이미지 라벨링이 여기 붙는다.
            raise ModuleFailed("vision_model", "온디바이스 비전 없음")
        if backend is None:
            raise ModuleFailed("no_backend", "쓸 수 있는 모델이 없다")

        found = identify(backend, model, inst.context.get("image", b""), inst.text)

        # 자택에서 애매하면 위로 올린다. 마지막 단계면 애매한 채로 답한다.
        if found["confidence"] < MIN_CONFIDENCE and inst.tier != "api":
            raise ModuleFailed("low_confidence",
                               f"{found['name']} {found['confidence']:.2f}")

        inst.context["found"] = found  # 기억에 남길 때 쓴다
        price = price_lookup(found) if price_lookup else ""
        return describe(found, price)

    return ModuleSpec(
        name="제품 검색",
        triggers=["이거 뭐야", "이게 뭐야", "제품", "시세", "얼마", "뭔지"],
        run=run,
        tiers=["phone", "pc", "api"],
        needs=["camera"],
    )


def _self_check() -> None:
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    import backends

    png = (b"\x89PNG\r\n\x1a\n" + b"\x00" * 40)
    jpg = b"\xff\xd8\xff" + b"\x00" * 20

    # 내용으로 형식을 가린다.
    assert media_type(png) == "image/png" and media_type(jpg) == "image/jpeg"
    try:
        media_type(b"not an image")
    except ModuleFailed as e:
        assert e.where == "image_format"
    else:
        raise AssertionError("모르는 형식이 통과했다")

    # 모델이 뭘 덧붙여도 JSON만 건져낸다.
    assert parse_json('{"name":"펜"}')["name"] == "펜"
    assert parse_json('```json\n{"name":"펜"}\n```')["name"] == "펜"
    assert parse_json('네, 알겠습니다.\n{"name":"펜"}\n도움이 되었길!')["name"] == "펜"
    for bad in ("그냥 말", '{"name": 깨짐'):
        try:
            parse_json(bad)
        except ModuleFailed:
            pass
        else:
            raise AssertionError(f"깨진 걸 통과시켰다: {bad}")

    class FakeBackend:
        reply = '{"name":"만년필","brand":"라미","category":"문구","confidence":0.9,"note":"검정"}'
        seen: dict = {}

        def chat(self, messages, model):
            self.seen = {"messages": messages, "model": model}
            if isinstance(self.reply, Exception):
                raise self.reply
            return self.reply

    fake = FakeBackend()
    mod = build(fake, "vision-model")

    # 폰에서는 바로 올려보낸다.
    inst = Instruction(text="이거 뭐야", context={"image": jpg})
    inst.tier = "phone"
    try:
        mod.run(inst)
    except ModuleFailed as e:
        assert e.where == "vision_model"
    else:
        raise AssertionError("폰에서 됐다고 한다")

    # PC에서 식별한다. 이미지가 실제로 실려 나간다.
    inst.tier = "pc"
    assert mod.run(inst) == "라미 만년필이야. 검정"
    parts = fake.seen["messages"][0]["content"]
    assert parts[-1]["media_type"] == "image/jpeg"
    assert base64.b64decode(parts[-1]["data"]) == jpg
    assert fake.seen["model"] == "vision-model"
    assert "이거 뭐야" in json.dumps(parts, ensure_ascii=False), "사용자 말이 안 실렸다"

    # 확신이 모자라면 위로 올린다.
    fake.reply = '{"name":"펜","confidence":0.3}'
    try:
        mod.run(inst)
    except ModuleFailed as e:
        assert e.where == "low_confidence", e.where
    else:
        raise AssertionError("애매한데 그냥 답했다")

    # 마지막 단계에서는 모자란 티를 내며 답한다.
    inst.tier = "api"
    assert mod.run(inst) == "펜인 것 같은데 확실하진 않아."

    # 백엔드가 죽으면 그 이유가 남는다 — 분석이 이걸 읽는다.
    fake.reply = backends.BackendError("engine down")
    try:
        mod.run(inst)
    except ModuleFailed as e:
        assert e.where == "vision_model" and "engine down" in str(e)

    # "없음"이라고 답해도 물건을 찾은 것으로 치지 않는다.
    for nothing in ('{"name":"없음","confidence":0.9}', '{"name":"","confidence":0.9}',
                    '{"name":"모름","confidence":0.5}'):
        fake.reply = nothing
        try:
            mod.run(inst)
        except ModuleFailed as e:
            assert e.where == "nothing_seen", e.where
        else:
            raise AssertionError(f"없는 걸 찾았다고 한다: {nothing}")

    # 사진이 없으면 모델을 부르지 않는다. 돈만 나간다.
    fake.reply = '{"name":"펜","confidence":0.9}'
    empty = Instruction(text="이거 뭐야")
    empty.tier = "pc"
    try:
        mod.run(empty)
    except ModuleFailed as e:
        assert e.where == "no_image"
    else:
        raise AssertionError("사진 없이 모델을 불렀다")

    # 글자 모델에 사진을 주면 막는다 — 조용히 지어낸 답이 제일 나쁜 실패다.
    class TextOnly(FakeBackend):
        sees_images = False

    blind = build(TextOnly(), "qwen-text")
    inst.tier = "pc"
    try:
        blind.run(inst)
    except ModuleFailed as e:
        assert e.where == "not_vision_model", e.where
    else:
        raise AssertionError("글자 모델이 사진을 봤다고 한다")

    # 백엔드가 아예 없으면 그대로 보고한다.
    bare = build()
    inst.tier = "pc"
    try:
        bare.run(inst)
    except ModuleFailed as e:
        assert e.where == "no_backend"

    # --- 진짜 HTTP로 한 바퀴 (규격 번역까지 확인) ---
    got: dict = {}

    class Vision(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_POST(self):
            got.update(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            body = json.dumps({"choices": [{"message": {"content":
                '{"name":"머그컵","brand":"","category":"주방","confidence":0.82,"note":"흰색"}'
            }}]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    srv = ThreadingHTTPServer(("127.0.0.1", 0), Vision)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    real = build(backends.OpenAICompatible(f"http://127.0.0.1:{srv.server_address[1]}/v1"),
                 "qwen2.5-vl")
    live = Instruction(text="이거 뭐야", context={"image": png})
    live.tier = "pc"
    assert real.run(live) == "머그컵이야. 흰색"
    assert got["messages"][0]["content"][-1]["image_url"]["url"].startswith(
        "data:image/png;base64,")
    assert live.context["found"]["category"] == "주방"
    srv.shutdown()
    srv.server_close()

    print("product_search self-check 통과")


if __name__ == "__main__":
    _self_check()
