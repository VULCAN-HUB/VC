# 구운 설치본이 **실제로 되는지** 본다.
#
# 창이 뜨는 것만으로는 모른다. 설치본에서 모델을 못 찾아 뜻 검색이 꺼진 채로 돌아도
# 창은 멀쩡히 뜬다(실제로 그랬다). 그래서 결과물을 들여다본다:
#
#   1. 창이 뜨는가, 몇 초 걸리는가
#   2. 기록을 **설치 폴더 밖**에 만드는가 (Program Files 에 깔면 못 쓴다)
#   3. 딸려 온 모델을 찾았는가 (뜻 벡터가 만들어졌는가)
param(
    [string]$App  = "C:\vcbuild\dist\VC",
    [string]$Data = "$env:TEMP\vc-check"
)
$ErrorActionPreference = "Stop"
if (Test-Path $Data) { Remove-Item $Data -Recurse -Force }
$env:VC_DATA = $Data           # 진짜 문서 폴더를 안 더럽힌다

Get-Process -Name VC -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Process "$App\VC.exe" -WorkingDirectory $App | Out-Null

# ⚠️ 함정: 창 핸들은 **프로세스 이름 전체를 훑어** 찾아야 한다. 부모만 보면
# 영원히 0일 수 있다(예전 배포에서 90초로 오측정한 적이 있다).
$sw = [Diagnostics.Stopwatch]::StartNew(); $h = 0
while ($sw.Elapsed.TotalSeconds -lt 90 -and $h -eq 0) {
    Start-Sleep -Milliseconds 300
    $all = Get-Process -Name VC -ErrorAction SilentlyContinue
    if (-not $all) { break }
    foreach ($x in $all) { if ($x.MainWindowHandle -ne 0) { $h = $x.MainWindowHandle } }
}
if ($h -eq 0) { Write-Host "  안됨  창이 안 떴다"; exit 1 }
Write-Host ("  된다  창 뜸 {0:N2}초" -f $sw.Elapsed.TotalSeconds)

# 뜻 벡터는 뒤에서 만든다. 조금 기다려 준다.
Start-Sleep -Seconds 20
Get-Process -Name VC -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Seconds 2

$ok = $true
foreach ($f in @("data\notes", "notes_index.db")) {
    if (Test-Path (Join-Path $Data $f)) { Write-Host "  된다  기록이 밖에 생겼다 — $f" }
    else { Write-Host "  안됨  $f 가 없다"; $ok = $false }
}
$leak = Get-ChildItem $App -Filter "*.db" -ErrorAction SilentlyContinue
if ($leak) { Write-Host "  안됨  설치 폴더에 자료가 샜다: $($leak.Name -join ', ')"; $ok = $false }
else { Write-Host "  된다  설치 폴더는 안 더럽혔다" }

# 뜻 벡터가 있으면 **모델을 찾았다는 뜻**이다.
$db = Join-Path $Data "notes_index.db"
if (Test-Path $db) {
    # 파이썬 조각을 여기 바로 쓰면 PowerShell 이 따옴표를 먹는다. 파일로 뺀다.
    $py = Join-Path $env:TEMP "vc-count.py"
    @'
import sqlite3, sys
c = sqlite3.connect(sys.argv[1])
try:
    print(c.execute("SELECT count(*) FROM vectors").fetchone()[0])
except Exception:
    print(-1)
'@ | Out-File $py -Encoding utf8
    $n = & python $py $db
    Remove-Item $py -Force
    if ([int]$n -gt 0) { Write-Host "  된다  뜻 벡터 $n 개 — 딸려 온 모델을 찾았다" }
    else { Write-Host "  안됨  뜻 벡터가 없다 — 모델을 못 찾았을 수 있다"; $ok = $false }
}
Remove-Item Env:\VC_DATA
if ($ok) { Write-Host "== 설치본 확인 통과" } else { Write-Host "== ★ 설치본에 문제 있음"; exit 1 }
