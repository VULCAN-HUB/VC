# VC 설치본 굽기.
#
#   .\build.ps1                      # 굽고 검사까지
#   .\build.ps1 -OutDir D:\어디       # 산출물 자리를 바꾼다
#   .\build.ps1 -SkipScan            # 백신 검사를 건너뛴다(빠르게 확인만 할 때)
#
# 왜 이렇게 하는지는 VC.spec 위쪽에 적어 뒀다. 여기서는 **경로 함정**만 짚는다:
# PyInstaller 는 한글이 든 경로에서 종종 어긋난다. 그래서 ASCII 정션을 걸어 두고
# 거기서 굽는다. 정션은 끝나면 지운다 — C 드라이브에 작업물을 남기지 않는다.
param(
    [string]$OutDir = "D:\프로젝트\_빌드파일",
    [switch]$SkipScan
)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Link = "C:\vcbuild"

# ★★ **두 굽기가 겹치면 둘 다 깨진다.** 같은 정션·같은 dist 를 쓰기 때문이다 —
# 먼저 것이 묶는 중에 뒤엣것이 정션을 지우고 다시 걸어, 둘 다 "파일을 못 찾는다" 로 끝났다.
# 실제로 그렇게 두 판을 날렸다. 자물쇠 파일 하나로 막는다.
$Lock = Join-Path $env:TEMP "vc-build.lock"
if (Test-Path $Lock) {
    $언제 = (Get-Item $Lock).LastWriteTime
    if (((Get-Date) - $언제).TotalMinutes -lt 30) {
        throw "이미 굽는 중이다 ($($언제.ToString('HH:mm:ss')) 에 시작). 끝나고 다시 해라. " +
              "정말 아니면 이 파일을 지워라: $Lock"
    }
    Remove-Item $Lock -Force          # 30분 넘은 것은 죽은 자물쇠로 본다
}
Set-Content -LiteralPath $Lock -Value (Get-Date).ToString("s") -Encoding utf8

# ★ **굽는 데 드는 시간을 찍는다.** 한 번 고칠 때마다 굽던 버릇을 고치려면(오너 2026-09-13)
# 굽기가 얼마짜리인지 눈에 보여야 한다. 모아서 한 번 굽는 것이 규칙이다.
$시계 = [System.Diagnostics.Stopwatch]::StartNew()

Write-Host "== 정션 걸기 $Link -> $Root"
if (Test-Path $Link) { cmd /c rmdir $Link | Out-Null }
cmd /c mklink /J $Link "$Root" | Out-Null
if (-not (Test-Path "$Link\eb.py")) { throw "정션이 안 걸렸다" }

try {
    # 판 번호는 paths.py 한 자리에만 있다. 여기서 읽어 version.txt 를 만든다 —
    # 안 그러면 exe 속성에 0.1.0.0 이 박히고, 쓰는 사람이 어느 판인지 못 가른다.
    $Ver = (& python -c "import sys; sys.path.insert(0, r'$Link'); import paths; print(paths.VERSION)").Trim()
    if ($Ver -notmatch '^\d+\.\d+\.\d+$') { throw "판 번호가 이상하다: '$Ver'" }
    Write-Host "== 판 v$Ver"
    $Tpl = Get-Content "$Link\version.txt.틀" -Raw -Encoding UTF8
    # 괄호로 통째로 묶는다. 안 묶으면 PowerShell 이 인자 셋으로 읽고 깨진다.
    $Nums = (($Ver -split '\.') -join ', ') + ', 0'
    $Tpl = $Tpl -replace '@@네자리@@', $Nums
    $Tpl = $Tpl -replace '@@판@@', "$Ver.0"
    $Tpl | Out-File "$Link\version.txt" -Encoding utf8 -NoNewline
    if ((Get-Content "$Link\version.txt" -Raw) -match '@@') { throw "틀에 안 채운 자리가 남았다" }

    Write-Host "== 아이콘 굽기"
    & python "$Link\tools\make_icon.py"
    if ($LASTEXITCODE -ne 0) { throw "아이콘 실패" }

    Write-Host "== 굽는 중 (몇 분 걸린다)"
    Push-Location $Link
    & python -m PyInstaller VC.spec --noconfirm --clean `
        --distpath "$Link\dist" --workpath "$Link\build"
    $code = $LASTEXITCODE
    Pop-Location
    if ($code -ne 0) { throw "빌드 실패 (종료 $code)" }

    $App = "$Link\dist\VC"
    if (-not (Test-Path "$App\VC.exe")) { throw "VC.exe 가 안 나왔다" }
    $MB = [math]::Round(((Get-ChildItem $App -Recurse -File |
          Measure-Object Length -Sum).Sum / 1MB), 1)
    Write-Host "== 크기 $MB MB"

    if (-not (Test-Path $OutDir)) { New-Item -ItemType Directory $OutDir | Out-Null }
    $Zip = Join-Path $OutDir "VC.zip"
    Write-Host "== 묶는 중 $Zip"
    if (Test-Path $Zip) { Remove-Item $Zip -Force }
    Compress-Archive -Path "$App\*" -DestinationPath $Zip -CompressionLevel Optimal

    # 무결성 확인용이자 **오탐 신고 근거**다. 백신에 걸렸을 때 이 값이 있어야
    # "우리가 낸 그 파일이 맞다"를 보일 수 있다.
    $sha = (Get-FileHash $Zip -Algorithm SHA256).Hash
    "$sha  VC.zip" | Out-File "$Zip.sha256" -Encoding utf8
    Write-Host "== SHA-256 $sha"
    "v$Ver  $sha" | Out-File (Join-Path $OutDir "판.txt") -Encoding utf8

    if (-not $SkipScan) {
        # **배포 전에 반드시 본다.** 행사 당일 백신에 막히면 되돌릴 방법이 없다.
        $mp = "$env:ProgramFiles\Windows Defender\MpCmdRun.exe"
        if (Test-Path $mp) {
            Write-Host "== Defender 검사"
            & $mp -Scan -ScanType 3 -File $App | Select-Object -Last 5
        } else {
            Write-Host "== Defender 를 못 찾았다 — 검사 건너뜀"
        }
    }
    # $MB 는 푼 폴더 크기다. 여기서 그걸 찍으면 zip 이 579MB 인 줄 알게 된다(실은 300MB).
    $ZipMB = [math]::Round((Get-Item $Zip).Length / 1MB, 1)
    Write-Host "== 끝. $Zip ($ZipMB MB · 풀면 $MB MB) · 굽는 데 $([math]::Round($시계.Elapsed.TotalMinutes,1))분"
}
finally {
    if (Test-Path $Link) { cmd /c rmdir $Link | Out-Null }
    # 자물쇠는 **깨져도 푼다** — 안 풀면 다음 굽기가 30분 동안 막힌다.
    if (Test-Path $Lock) { Remove-Item $Lock -Force -ErrorAction SilentlyContinue }
    Write-Host "== 정션 치움"
}
