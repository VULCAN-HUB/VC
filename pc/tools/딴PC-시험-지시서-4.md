# VC v0.1.3 재시험 — 지시서 4

3차 보고서가 이번에도 원인을 갈랐다. 특히 둘:

- **「새 파일이 생기면 밀린 변경이 한꺼번에 들어온다」** — 이 한 문장으로
  내가 2차에 「연/월 폴더까지 감시」로 고친 것이 **엉뚱한 데**였다는 걸 알았다.
  폴더 깊이 문제가 아니라, 폴더 감시가 **「고쳐짐」을 아예 안 알려 주는** 것이었다.
- **「조각 창이 v0.1.1·v0.1.2 에서 크기·위치가 똑같이 재현된다」** — 「제 조작의
  산물일 수 있다」에서 여기까지 좁혀 준 덕에 실재를 확정하고 범인을 찾았다.

## v0.1.3 에서 고친 여섯

| # | 무엇 | 진짜 원인 |
|---|---|---|
| 1 | 밖에서 고친 글이 안 옴 | 폴더 감시는 **「생김」만** 알린다. 3초마다 직접 묻는다 |
| 2 | `[[` 목록 Esc (**세 번째**) | 창 **단축키**가 글상자보다 먼저 먹었다. 앞선 두 고침은 **실행조차 안 됐다** |
| 3 | 되돌리기 직전 글 실종 | 이력 5분 묶음에 먹혔다. 되돌리기에서만 무시 |
| 4 | 할 일 체크가 풀림 | 파일·읽기 화면만 고치고 **고치는 칸**을 안 고쳤다 |
| 5 | 조각 창 · 창 닫아도 프로세스 생존 | 「지우기」 위젯이 **어느 칸에도 안 들어가** 있었다. 부모 없는 위젯을 `show()` 하면 독립 창이 된다 |
| 6 | 고치는 중 예고 없이 편집 종료 | 이제 안 건드리고 안내만 |

---

## 0) 받기

`https://github.com/VULCAN-HUB/VC/releases/tag/v0.1.3`

```powershell
Get-FileHash VC.zip -Algorithm SHA256
# 963d14b56f8529ba289a49ee0457bd012046ac250908291d44d06b5e831a0a34
```

```powershell
$env:VC_DATA = "$env:USERPROFILE\vc시험4"
$N = "$env:VC_DATA\data\notes"
.\VC.exe          # 반드시 이 창에서
```

씨앗은 지시서 2의 8개를 그대로 쓰면 된다(3번 시험에 필요).

---

## 1) ★ 조각 창 · 프로세스 종료 (5번 — 재현법을 이미 아는 것)

**3차에서 그쪽이 확립한 절차 그대로.**

1. `Ctrl+N` 을 누른다
2. 화면 어디에도 **「지우기」만 든 작은 창(136x62)이 안 떠야 한다**
3. 최상위 창 개수를 센다:

```powershell
Add-Type @'
using System;using System.Runtime.InteropServices;using System.Text;
public class W {
  [DllImport("user32.dll")] public static extern bool EnumWindows(EnumWindowsProc f, IntPtr l);
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
  [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint p);
  [DllImport("user32.dll")] public static extern int GetWindowText(IntPtr h, StringBuilder s, int n);
  public delegate bool EnumWindowsProc(IntPtr h, IntPtr l);
}
'@
$pid_ = (Get-Process VC).Id
$found = @()
[W]::EnumWindows({ param($h,$l)
  $p = 0; [W]::GetWindowThreadProcessId($h, [ref]$p) | Out-Null
  if ($p -eq $pid_ -and [W]::IsWindowVisible($h)) {
    $sb = New-Object Text.StringBuilder 256
    [W]::GetWindowText($h, $sb, 256) | Out-Null
    $script:found += "$h  $($sb.ToString())"
  }
  return $true
}, [IntPtr]::Zero) | Out-Null
$found
```

**보이는 창이 1개여야 한다.** 2개 이상이면 그 목록을 그대로 보내 달라.

4. 주 창을 **평범하게 X 로 닫는다**(창 API 안 쓰고)
5. 프로세스가 사라졌는지:

```powershell
Get-Process VC -ErrorAction SilentlyContinue
Get-Content "$env:VC_DATA\vc-기록.log" -Encoding UTF8 -Tail 3
```

**아무것도 안 나오고 `끔 (0)` 이 찍혀 있으면 통과.**

---

## 2) ★ `[[` Esc (세 번째 실패했던 것)

VC 다시 켜고, 항목 하나 열어 「고치기」.

| 누름 | 기대 |
|---|---|
| `[[` 치고 목록 뜬 상태에서 **Esc 한 번** | **목록이 닫힌다.** 카드는 그대로 열려 있어야 한다 |
| 이어서 **Esc 한 번 더** | 이번엔 카드가 닫힌다 |
| 목록 뜬 상태에서 **아래방향키** | 선택이 움직인다 (**계속 돼야 한다**) |
| 목록 뜬 상태에서 **엔터** | 고른 제목이 본문에 들어가고 `]]` 까지 닫힌다 |

두 번째 줄이 중요하다 — **Esc 한 번에 목록과 카드가 같이 닫히면 안 된다.**
(단축키가 둘 다 먹어 버리는 실수를 막았는지 보는 것)

3차에 그쪽이 「새 팝업에서 방향키를 안 누르고 Esc 만」 으로 재현해 준 그 방법도
한 번 해 달라.

---

## 3) ★ 밖에서 고친 글이 오나 (3차에 규칙을 찾아낸 것)

**3차에 세운 규칙이 깨졌는지를 본다.** 그때는 「새 파일이 생겨야 밀린 게 들어왔다」.

항목 하나를 화면에 **읽기 모드로** 열어 둔 채로:

```powershell
$f = (Get-ChildItem $N -Recurse -Filter "허리 통증.md").FullName
Add-Content $f "`n밖에서덧붙임1" -Encoding UTF8
```

**새 파일은 절대 만들지 말고** 시간을 잰다. 3차에는 39초에도 안 왔다.

| 시점 | 봐야 할 것 |
|---|---|
| 5초 | 열린 카드에 `밖에서덧붙임1` 이 있나 |
| 10초 | 없으면 아직인가 |
| 30초 | 그래도 없으면 실패 |

**기대: 3초쯤에 들어온다.**

검색으로도 확인:

```powershell
# VC 검색칸에 「밖에서덧붙임1」 치기 -> 허리 통증이 나와야 한다
```

### 3-1) 세 경우 다시

| 경우 | 기대 |
|---|---|
| 읽기 모드로 열어 둠 | 3초 안에 화면에 나타난다 |
| **고치기 모드로 열어 둠** | **읽기로 안 튕긴다.** 「밖에서도 고쳤어… 다 쓰고 「읽기」를 누르면」 안내가 뜬다. 치던 글 그대로 |
| 안 열어 둔 항목 | 열면 새 내용 |

가운데가 3차에 「안내 없이 편집이 끝난다」로 걸렸던 자리다.

---

## 4) 되돌리기 직전 글 (3차 3순위)

「허리 통증」을 열어서:

1. 본문 끝에 `되돌리기전글` 한 줄 넣고 저장
2. **바로 이어서**(5분 안에) 「지난 판」 콤보에서 옛 판으로 **되돌린다**
3. 확인:

```powershell
Get-ChildItem "$N\..\..\data\notes\.이력" -Recurse -Filter *.md |
  ForEach-Object { "$($_.Name)  $((Get-Content $_.FullName -Raw -Encoding UTF8) -match '되돌리기전글')" }
```

**`되돌리기전글` 이 이력 어딘가에 있어야 한다.** 없으면 실패.

3차에는 5분 묶음에 먹혀서 파일에도 이력에도 없었다.
「지난 판」 콤보 개수도 되돌리기 뒤에 **늘어야** 한다.

---

## 5) 할 일 체크가 안 풀리나 (3차 4순위)

1. 본문에 넣고 저장:
   ```
   - [ ] 첫째
   - [ ] 둘째
   ```
2. 읽기 모드에서 **첫째 네모 클릭** → ☑ 로 바뀜
3. **「고치기」로 들어가서 다른 줄을 하나 고치고** 「읽기」로 나온다
4. 파일 확인:

```powershell
Get-Content (Get-ChildItem $N -Recurse -Filter "*.md" | Where-Object { (Get-Content $_.FullName -Raw) -match '첫째' } | Select-Object -First 1).FullName -Encoding UTF8
```

**`- [x] 첫째` 가 그대로 있어야 한다.** 3차에는 `- [ ]` 로 풀렸다.

---

## 6) 되짚기 — v0.1.2 성과가 그대로인가

이번엔 고친 곳이 여섯 군데라 망가뜨렸을 위험이 높다. **여기가 제일 중요하다.**

| 확인 | 기대 |
|---|---|
| `Ctrl+N` → 제목 치고 → 본문 쓰고 저장 | 파일에 본문이 있다 |
| 제목 **두 번** 바꾸고 본문 저장 | 파일에 본문이 있다 |
| 「지난 판」 콤보 | 세 번 고치면 나타난다 |
| `이미지 다듬는 법` 검색 | 안 죽는다. 1등 = 사진 보정 순서 |
| 빈 항목 3개 만들고 검색 | 결과에 빈 항목 없음 |
| 돋보기 · 확인창 · `＋ 새 항목` | 3차와 같음 |

---

## 7) 막 굴리기 — 3초 폴링이 붙었으니 다시

**새로 넣은 3초 폴링이 다른 걸 망가뜨리지 않았는지**가 이번 난타의 목적이다.

VC 켜 둔 채 밖에서 40개 쓰기를 두 번 돌리고, 그동안 화면에서
「만들기 → 제목 바꾸기 → 본문 쓰기 → 저장」을 여섯 번.

```powershell
1..40 | ForEach-Object {
  Set-Content (Join-Path $N "난타-$_.md") "내용 $_" -Encoding UTF8
  Start-Sleep -Milliseconds 250
}
```

끝나고:

```powershell
Get-ChildItem $N -Recurse -Filter *.tmp
(Get-ChildItem $N -Recurse -Filter *.md | Where-Object { $_.FullName -notlike "*\.이력\*" }).Count
Get-Content "$env:VC_DATA\vc-죽음.log" -Encoding UTF8 -Tail 40
```

- 쓴 글 6개가 **전부** 파일에 들어갔나
- `.tmp` 0개인가 · 화면 항목 수 = 실제 `.md` 수인가
- **화면이 굼떠지지 않았나** (3초마다 훑으니 체감으로만이라도)

---

## 8) 마지막 · 뒷정리

```powershell
.\VC.exe --report
Remove-Item $env:VC_DATA -Recurse -Force
```

3차에 물어본 잔재 둘(`2026\08\사진 보정 순서.md`, `새 항목.md`) — **지워도 된다.**

---

## 돌려줄 것

1. **★ 1번** — 조각 창 떴나 · 최상위 창 개수 · X 로 닫았을 때 프로세스 죽었나
2. **★ 2번** — Esc 한 번에 목록만 닫혔나 · 두 번째 Esc 에 카드 닫혔나 · 방향키·엔터 그대로인가
3. **★ 3번** — 새 파일 없이 몇 초 만에 왔나 · 세 경우 각각
4. 4번 — `되돌리기전글` 이 이력에 있나
5. 5번 — `- [x]` 가 살아남았나
6. 6번 되짚기 여섯 줄
7. 7번 — 잃은 글 · `.tmp` · 항목 수 · 굼뜸
8. `VC-진단-....zip`

세 번 다 그랬듯 **본 대로만, 안 해 본 것은 「안 해 봄」**. 그게 매번 원인을 짚어 줬다.
특히 **「고쳤다는데 증상이 그대로」** 는 그냥 그렇게 적어 달라 — 3차의 그 한 줄이
내가 엉뚱한 데를 고치고 있었다는 걸 알려 줬다.
