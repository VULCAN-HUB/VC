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

Write-Host "== 정션 걸기 $Link -> $Root"
if (Test-Path $Link) { cmd /c rmdir $Link | Out-Null }
cmd /c mklink /J $Link "$Root" | Out-Null
if (-not (Test-Path "$Link\eb.py")) { throw "정션이 안 걸렸다" }

try {
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
    Write-Host "== 끝. $Zip ($MB MB)"
}
finally {
    if (Test-Path $Link) { cmd /c rmdir $Link | Out-Null }
    Write-Host "== 정션 치움"
}
