"""바깥 AI API 키를 운영체제 보관소에 둔다 (오너 결정 1 추천: 윈도우 자격 증명 관리자 · 맥 키체인).

★★ **키를 `eb_config.json` 평문에 두지 않는다.** 설정 파일은 진단 묶음·백업·동기화로 쉽게 밖에 나간다.
보관소가 없는 운영체제(리눅스 등)에서는 `None` 을 돌려주고, 부르는 쪽이 설정의 평문을 그대로 쓴다(안 멈추는 쪽).
새 의존성은 안 쓴다 — 윈도우는 advapi32(ctypes), 맥은 `security` 명령.
"""

from __future__ import annotations

import os
import subprocess
import sys

앞말 = "VC:"


def _win():
    import ctypes
    from ctypes import wintypes

    class CREDENTIAL(ctypes.Structure):
        _fields_ = [("Flags", wintypes.DWORD), ("Type", wintypes.DWORD),
                    ("TargetName", wintypes.LPWSTR), ("Comment", wintypes.LPWSTR),
                    ("LastWritten", wintypes.FILETIME), ("CredentialBlobSize", wintypes.DWORD),
                    ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)), ("Persist", wintypes.DWORD),
                    ("AttributeCount", wintypes.DWORD), ("Attributes", ctypes.c_void_p),
                    ("TargetAlias", wintypes.LPWSTR), ("UserName", wintypes.LPWSTR)]

    adv = ctypes.WinDLL("advapi32", use_last_error=True)
    adv.CredWriteW.argtypes = [ctypes.POINTER(CREDENTIAL), wintypes.DWORD]
    adv.CredReadW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                              ctypes.POINTER(ctypes.POINTER(CREDENTIAL))]
    adv.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
    adv.CredFree.argtypes = [ctypes.c_void_p]
    return ctypes, adv, CREDENTIAL


def available() -> bool:
    return os.name == "nt" or sys.platform == "darwin"


def put(name: str, value: str) -> bool:
    if os.name == "nt":
        ctypes, adv, CREDENTIAL = _win()
        blob = value.encode("utf-16-le")
        buf = (ctypes.c_ubyte * len(blob)).from_buffer_copy(blob)
        cred = CREDENTIAL(Type=1, TargetName=앞말 + name, CredentialBlobSize=len(blob),
                          CredentialBlob=buf, Persist=2, UserName="VC")   # 1 = GENERIC, 2 = LOCAL_MACHINE
        return bool(adv.CredWriteW(ctypes.byref(cred), 0))
    if sys.platform == "darwin":
        return subprocess.run(["security", "add-generic-password", "-U", "-a", "VC",
                               "-s", 앞말 + name, "-w", value], capture_output=True).returncode == 0
    return False


def get(name: str) -> str | None:
    if os.name == "nt":
        ctypes, adv, CREDENTIAL = _win()
        p = ctypes.POINTER(CREDENTIAL)()
        if not adv.CredReadW(앞말 + name, 1, 0, ctypes.byref(p)):
            return None
        try:
            c = p.contents
            return bytes(c.CredentialBlob[:c.CredentialBlobSize]).decode("utf-16-le")
        finally:
            adv.CredFree(p)
    if sys.platform == "darwin":
        r = subprocess.run(["security", "find-generic-password", "-a", "VC", "-s", 앞말 + name, "-w"],
                           capture_output=True, text=True)
        return r.stdout.rstrip("\n") if r.returncode == 0 else None
    return None


def delete(name: str) -> bool:
    if os.name == "nt":
        _, adv, _ = _win()
        return bool(adv.CredDeleteW(앞말 + name, 1, 0))
    if sys.platform == "darwin":
        return subprocess.run(["security", "delete-generic-password", "-a", "VC", "-s", 앞말 + name],
                              capture_output=True).returncode == 0
    return False


def 키이름(backend_cfg: dict) -> str:
    return f"backend:{backend_cfg.get('kind', '')}"


def 평문키옮기기(backend_cfg: dict) -> bool:
    """설정에 평문 `api_key` 가 있으면 보관소로 옮기고 설정에서는 지운다. 옮겼으면 참(설정을 다시 써야 한다).

    못 옮기면(보관소 없음·쓰기 실패) 설정을 그대로 둔다 — 키를 잃는 것보다 평문이 낫다.
    """
    키 = backend_cfg.get("api_key")
    if not isinstance(키, str) or not 키 or not available():
        return False
    if not put(키이름(backend_cfg), 키) or get(키이름(backend_cfg)) != 키:
        return False
    backend_cfg.pop("api_key", None)
    backend_cfg["api_key_in"] = "keystore"
    return True


def 키꺼내기(backend_cfg: dict) -> str:
    """설정의 평문이 있으면 그것, 없으면 보관소. 둘 다 없으면 빈 글."""
    return backend_cfg.get("api_key") or (get(키이름(backend_cfg)) if available() else None) or ""


def _self_check() -> None:
    import secrets

    if not available():
        assert get("없음") is None and not put("없음", "x")
        print("keystore self-check 통과 (보관소 없는 운영체제)")
        return
    이름 = "시험-" + secrets.token_hex(6)
    가짜키 = "sk-시험-" + secrets.token_hex(8)
    try:
        assert get(이름) is None
        assert put(이름, 가짜키) and get(이름) == 가짜키, "보관소에 넣은 키를 못 꺼낸다"
        assert put(이름, 가짜키 + "2") and get(이름) == 가짜키 + "2", "같은 이름에 다시 넣으면 안 바뀐다"
    finally:
        delete(이름)
    assert get(이름) is None, "지운 키가 남는다"

    # 평문 옮기기: 설정에서 사라지고 꺼내기는 그대로 된다
    kind = "시험종류-" + secrets.token_hex(4)
    설정 = {"kind": kind, "api_key": 가짜키}
    try:
        assert 평문키옮기기(설정), "평문 키를 못 옮긴다"
        assert "api_key" not in 설정 and 설정["api_key_in"] == "keystore", 설정
        assert 키꺼내기(설정) == 가짜키, "옮긴 키를 못 꺼낸다"
        assert not 평문키옮기기(설정), "옮길 것이 없는데 참"
    finally:
        delete(키이름(설정))
    print("keystore self-check 통과")


if __name__ == "__main__":
    if "--check" in sys.argv:
        _self_check()
