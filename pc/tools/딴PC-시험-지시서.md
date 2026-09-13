# VC 낯선 PC 시험 — 3번(뜻 검색) · 5번(막 굴리기)

이 PC에는 **소스가 없다.** 압축 푼 `VC.exe` 폴더와 기록 폴더뿐이다.
파이썬도 없다고 보고, **PowerShell 과 GUI 만으로** 한다.

## 0) 먼저 자리 확인

```powershell
.\VC.exe --doctor
$D = (Get-Content "$env:USERPROFILE\Documents\VC\vc-진단.json" -Encoding UTF8 |
      ConvertFrom-Json).'기록 자리'
$N = "$D\data\notes"
$D; $N; Test-Path $N
```

`$D` 가 안 잡히면 `Documents\VC` 와 `문서\VC` 둘 다 봐라. 이 PC 에서 실제로
`~/Documents` 와 탐색기 「문서」가 **서로 다른 폴더**였다.

기록 파일은 `.md` 다. **사람 개인정보를 새로 넣지 마라** — 아래 씨앗만 쓴다.

---

## 3번 — 뜻 검색

**무엇을 보나**: 낱말이 하나도 안 겹쳐도 찾아지는가. 낱말 검색이면 0건이 나와야
정상인 질문을 던져서, 뜻 검색이 진짜 도는지 가른다.

### (1) 씨앗 8개를 파일로 깐다

VC 를 **끈 상태**에서:

```powershell
$seed = @{
 "사진 보정 순서.md"   = "촬영본을 고를 때는 노출부터 맞추고, 그 다음 흰 균형을 잡는다. 마지막에 잡티를 지운다."
 "달리기 기록.md"      = "아침에 8km 를 뛰었다. 무릎이 조금 아파서 속도를 줄였다."
 "전세 계약 준비.md"   = "등기부등본을 떼고 근저당을 확인한다. 확정일자는 이사 당일에 받는다."
 "김치찌개 끓이기.md"  = "묵은지를 먼저 볶다가 돼지고기를 넣는다. 물은 나중에 붓는다."
 "면접 준비.md"        = "지원한 회사의 최근 소식을 훑고, 내가 한 일을 숫자로 말할 수 있게 정리한다."
 "노트북 발열.md"      = "바닥에 받침을 대고 먼지를 불어냈다. 팬 소리가 줄었다."
 "제주 여행 계획.md"   = "삼일치 일정을 짜고 숙소를 먼저 잡는다. 렌터카는 성수기라 서두른다."
 "허리 통증.md"        = "오래 앉아 있으면 뻐근하다. 한 시간마다 일어나서 걷기로 했다."
}
foreach ($k in $seed.Keys) {
  Set-Content -Path (Join-Path $N $k) -Value $seed[$k] -Encoding UTF8
}
```

### (2) VC 를 켠다

색인이 붙고 뜻 벡터가 만들어질 시간이 필요하다. **처음 한 번은 몇 초 걸린다.**
왼쪽 위 숫자가 `항목 09` (VC 포함) 로 늘면 색인은 붙은 것이다.

### (3) 이 여섯 개를 검색칸에 그대로 친다

| # | 칠 말 | 나와야 할 것 | 왜 이 말인가 |
|---|---|---|---|
| 1 | `이미지 다듬는 법` | 사진 보정 순서 | 「사진」·「보정」 한 글자도 안 겹침 |
| 2 | `무릎 아플 때` | 달리기 기록 | 「달리기」 안 겹침 |
| 3 | `집 빌릴 때 확인할 것` | 전세 계약 준비 | 「전세」·「계약」 안 겹침 |
| 4 | `저녁 뭐 해먹지` | 김치찌개 끓이기 | 음식이라는 것만 같음 |
| 5 | `컴퓨터가 뜨겁다` | 노트북 발열 | 「노트북」·「발열」 안 겹침 |
| 6 | `등이 결린다` | 허리 통증 | 「허리」·「통증」 안 겹침 |

**적을 것**: 각 질문마다 ①맨 위에 뜬 제목 ②맞았나 ③몇 초 걸렸나.

6개 중 **4개 이상 맨 위**면 통과. 3개 이하면 실패로 적고 `--report` 를 뜬다.

> 0건만 나오면 뜻 검색이 꺼진 것이다. `--doctor` 의 `임베더 됨` 을 다시 봐라.

---

## 5번 — 막 굴리기

**목표는 하나: 안 죽는 것.** 값진 결과는 "죽었다" 쪽이다. 죽으면 즉시 멈추고
`vc-죽음.log` 를 통째로 챙긴다.

### (A) 사람이 손으로 — 화면 쪽 (5분)

VC 켠 채로 **빠르게 아무렇게나**. 각 동작 사이에 기다리지 마라.

1. `Ctrl+N` 여러 번 연타
2. 제목칸에 한글 치다가 다 지우고 다시 치기
3. 「고치기」 눌렀다 껐다 반복
4. 본문에 `[[` 쳐서 목록 띄운 채로 **위/아래/엔터/Esc** 마구
5. 「지우기」로 지운 뒤 **바로 뒤로 가기**(Alt+←) 눌러 지워진 항목으로 돌아가기
6. 「곁에 띄우기」 켠 채로 다른 항목 여러 개 빠르게 클릭
7. 「지난 판」 콤보를 열어 이 판 저 판 왔다갔다
8. 목차 항목 마구 클릭
9. 검색칸에 `"` `*` `((` `한글 AND` 같은 **깨진 검색어** 넣고 엔터
10. 창 크기를 아주 작게 줄였다가 최대화 (**빈 화면 상태에서도 한 번**)

10번이 특히 중요하다 — 예전에 여기서 프로세스가 통째로 죽었다.

### (B) Claude 가 스크립트로 — 파일 쪽 (이게 더 잘 잡는다)

**VC 를 켜 둔 채로** 돌린다. 밖에서 파일을 흔드는 동안 화면이 따라오는지를 본다.
실제 사용에서 옵시디언·동기화·백신이 하는 짓이다.

```powershell
$rand = [Random]::new(20260829)
1..120 | ForEach-Object {
  $i = $_
  $f = Join-Path $N ("난타-{0}.md" -f $i)
  switch ($rand.Next(6)) {
    0 { Set-Content $f "내용 $i`n[[사진 보정 순서]]" -Encoding UTF8 }
    1 { if (Test-Path $f) { Remove-Item $f -Force } }
    2 { $g = Join-Path $N ("난타-{0}-이름바꿈.md" -f $i)
        if (Test-Path $f) { Move-Item $f $g -Force } }
    3 { $sub = Join-Path $N "하위폴더"
        if (-not (Test-Path $sub)) { New-Item -ItemType Directory $sub | Out-Null }
        Set-Content (Join-Path $sub "옮긴글-$i.md") "폴더 안 $i" -Encoding UTF8 }
    4 { Set-Content $f ("---`ntype: note`ndate: 2026-08-29`n---`n`n본문 $i") -Encoding UTF8 }
    5 { Add-Content $f "덧붙임 $i" -Encoding UTF8 }
  }
  Start-Sleep -Milliseconds 120
}
```

돌아가는 동안 **화면도 같이 만져라** (항목 클릭·검색·고치기).

### (C) 끝나고 확인

```powershell
Get-ChildItem $N -Recurse -Filter *.tmp        # 0개여야 한다
Get-ChildItem $N -Recurse -Filter "*못 쓴 글*"  # 있으면 그 이름 적기
Get-Content "$D\vc-죽음.log" -Encoding UTF8 -Tail 60
```

- `.tmp` 가 남아 있으면 → **저장이 중간에 끊긴 것.** 적어라.
- VC 화면의 `항목 NN` 숫자와 실제 `.md` 개수가 **크게 다르면** 색인이 어긋난 것:

```powershell
(Get-ChildItem $N -Recurse -Filter *.md | Where-Object { $_.FullName -notlike "*\.이력\*" }).Count
```

### (D) 뒷정리

```powershell
Get-ChildItem $N -Recurse -Filter "난타-*.md" | Remove-Item -Force
Remove-Item (Join-Path $N "하위폴더") -Recurse -Force -ErrorAction SilentlyContinue
```

---

## 마지막 — 무조건 이거

```powershell
.\VC.exe --report
```

`기록자리\VC-진단-....zip` 이 나온다. **잘 됐어도 보낸다.**
(토큰·사용자 이름·기록 내용은 안 들어간다. 만든 사람이 검사로 강제해 둠.)

## 돌려줄 것

1. 3번 표 — 여섯 질문의 맨 위 결과·맞았나·걸린 시간
2. 5번 — 죽었나(어느 동작에서), `.tmp` 남았나, 「못 쓴 글」 생겼나, 항목 수 대 `.md` 수
3. `vc-죽음.log` 에 새로 찍힌 줄
4. `VC-진단-....zip`

**추측은 적지 마라.** 본 대로만 적고, 안 해 본 것은 "안 해 봄" 이라고 적는다.
