# 공유폴더에 새 ★ 파일이 오면 한 줄씩 알린다 (만든 쪽 세션의 Monitor 가 읽는다).
# 만든 쪽이 올리는 ★답- · ★판-올렸다- 는 빼고, 시험 쪽이 올리는 것만 알린다.
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$share = "\\192.168.1.4\점검보고서"
$mine = '^★(답|판-올렸다)-'
$seen = @{}
$down = $false
function Look { Get-ChildItem -LiteralPath $share -File -ErrorAction Stop | Where-Object { $_.Name -like '★*' -and $_.Name -notmatch $mine } }
try { Look | ForEach-Object { $seen[$_.Name] = $_.LastWriteTime } } catch {}
Write-Output "감시 시작 — 지금 ★ 파일 $($seen.Count)개는 이미 본 것으로 둔다"
while ($true) {
    Start-Sleep -Seconds 60
    try {
        $now = Look
        if ($down) { Write-Output "공유폴더 다시 붙음"; $down = $false }
        foreach ($f in $now) {
            if (-not $seen.ContainsKey($f.Name)) { Write-Output "새 파일: $($f.Name) ($([math]::Round($f.Length/1KB,1))KB)" }
            elseif ($seen[$f.Name] -ne $f.LastWriteTime) { Write-Output "고쳐짐: $($f.Name)" }
            $seen[$f.Name] = $f.LastWriteTime
        }
    } catch {
        if (-not $down) { Write-Output "★ 공유폴더가 안 붙는다 — 오너에게 알릴 것: $($_.Exception.Message)"; $down = $true }
    }
}