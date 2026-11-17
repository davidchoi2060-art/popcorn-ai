<#
.SYNOPSIS
  윈윈(팝콘PC) 가격을 중계기로 조회해 CSV 로 저장한다. 수동 실행과 작업 스케줄러 자동 실행에 쓴다.

.DESCRIPTION
  https://dev.popcornai.co.kr/api/mall-ai-gateway/price 를 부른다. 읽기 전용이다.
  사무실·집처럼 허용된 IP 에서만 동작한다. 그 밖에서는 403 으로 끝난다.

  - 상품번호는 50개씩 나눠 묻고, 묶음 사이에 1.2초 쉰다(중계기는 1초에 1회만 받는다).
  - 429(다른 조회 진행 중)는 2초 쉬고 최대 3번 다시 묻는다. 다른 오류는 다시 묻지 않는다.
  - 결과는 엑셀에서 바로 열리는 CSV(UTF-8 BOM)다. 열은 상품번호·상품명·가격·판매상태·최대수량이다(2026-11-17 윈윈 응답 변경).
  - 실행 기록은 OutDir\mall_price_export.log 에 한 줄씩 남는다(건수와 오류만, 값은 남기지 않는다).

.PARAMETER Codes
  쉼표로 구분한 상품번호. 예: "124401,124407"

.PARAMETER InputFile
  상품번호 목록 파일. 한 줄에 하나 또는 쉼표·공백 구분. # 으로 시작하는 줄은 무시한다.

.PARAMETER OutDir
  CSV 를 저장할 폴더. 없으면 만든다. 기본은 문서\윈윈가격.

.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File mall_price_export.ps1 -Codes "124401,124407"

.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File mall_price_export.ps1 -InputFile "C:\윈윈가격\상품목록.txt" -OutDir "C:\윈윈가격"
#>
[CmdletBinding()]
param(
    [string]$Codes = "",
    [string]$InputFile = "",
    [string]$OutDir = (Join-Path ([Environment]::GetFolderPath("MyDocuments")) "윈윈가격"),
    [string]$BaseUrl = "https://dev.popcornai.co.kr/api/mall-ai-gateway/price"
)

$ErrorActionPreference = "Stop"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$ChunkSize = 50
$PauseSeconds = 1.2

if (-not (Test-Path $OutDir)) { New-Item -ItemType Directory -Force -Path $OutDir | Out-Null }
$LogFile = Join-Path $OutDir "mall_price_export.log"

function Write-Log([string]$Text) {
    $line = "{0}  {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Text
    Add-Content -Path $LogFile -Value $line -Encoding UTF8
    Write-Host $line
}

# ---- 상품번호 모으기
$raw = @()
if ($Codes) { $raw += $Codes }
if ($InputFile) {
    if (-not (Test-Path $InputFile)) { Write-Log "실패: 목록 파일이 없습니다 ($InputFile)"; exit 2 }
    $raw += Get-Content -Path $InputFile -Encoding UTF8 | Where-Object { $_ -notmatch '^\s*#' }
}
$list = New-Object System.Collections.Generic.List[string]
$seen = @{}
foreach ($token in (($raw -join "`n") -split '[\s,;]+')) {
    if (-not $token) { continue }
    if ($token -notmatch '^[1-9][0-9]{0,11}$') { Write-Log "실패: 숫자가 아닌 상품번호 ($token)"; exit 2 }
    if (-not $seen.ContainsKey($token)) { $seen[$token] = $true; $list.Add($token) }
}
if ($list.Count -eq 0) { Write-Log "실패: 상품번호가 없습니다. -Codes 또는 -InputFile 을 주십시오."; exit 2 }

function Get-Amount($a) {
    if ($null -eq $a) { return "" }
    if ($a.status -eq "ok" -or $a.status -eq "zero") { return $a.value }
    return ""
}

function Invoke-Gateway([string[]]$Chunk) {
    $url = $BaseUrl + "?pd_no=" + ($Chunk -join ",")
    for ($try = 1; $try -le 4; $try++) {
        try {
            return Invoke-RestMethod -Uri $url -Method Get -TimeoutSec 30 -Headers @{ Accept = "application/json" }
        } catch {
            $status = 0
            if ($_.Exception.Response) { $status = [int]$_.Exception.Response.StatusCode }
            if ($status -eq 429 -and $try -lt 4) { Start-Sleep -Seconds 2; continue }
            $hint = switch ($status) {
                403 { "허용되지 않은 접속 위치(이 PC의 공인 IP를 관리자에게 등록 요청)" }
                404 { "조회 기능이 꺼져 있음" }
                429 { "다른 조회가 계속 진행 중" }
                502 { "윈윈 API 실패" }
                0   { "서버에 연결하지 못함(인터넷 연결 확인)" }
                default { "상태 $status" }
            }
            throw "조회 실패: $hint"
        }
    }
}

# ---- 조회
$rows = New-Object System.Collections.Generic.List[object]
$missing = 0
try {
    for ($i = 0; $i -lt $list.Count; $i += $ChunkSize) {
        if ($i -gt 0) { Start-Sleep -Milliseconds ([int]($PauseSeconds * 1000)) }
        $chunk = $list.GetRange($i, [Math]::Min($ChunkSize, $list.Count - $i)).ToArray()
        $data = Invoke-Gateway $chunk
        foreach ($it in $data.items) {
            # 2026-11-17 윈윈 응답 변경: 내부 가격 열(원가·딜러가·시중가·소비자가·재고값)은 더 오지 않는다.
            # 없는 번호는 not_found 로 온다. 판매상태는 윈윈이 준 값 그대로이고 이 스크립트가 판정한 값이 아니다.
            if (-not $it.found) { $missing++ }
            $maxQty = ""
            if ($it.max_qty -and $it.max_qty.status -eq "ok") { $maxQty = $it.max_qty.value }
            $rows.Add([pscustomobject][ordered]@{
                "조회시각"   = (Get-Date -Format "yyyy-MM-dd HH:mm")
                "윈윈조회시각" = $data.checked_at
                "상품번호"   = $it.pd_no
                "응답"       = $(if ($it.found) { "있음" } elseif ($it.lookup -eq "not_found") { "윈윈에 없는 번호" } else { "윈윈 응답에서 빠짐" })
                "상품명"     = $it.name
                "가격"       = Get-Amount $it.price
                "판매상태(윈윈 값 그대로)" = $it.status_raw
                "최대수량"   = $maxQty
            })
        }
    }
} catch {
    Write-Log ("실패: {0} (요청 {1}건)" -f $_.Exception.Message, $list.Count)
    exit 1
}

$file = Join-Path $OutDir ("윈윈가격_{0}.csv" -f (Get-Date -Format "yyyyMMdd_HHmm"))
$rows | Export-Csv -Path $file -NoTypeInformation -Encoding UTF8
Write-Log ("완료: 요청 {0}건, 응답 없음 {1}건 -> {2}" -f $list.Count, $missing, $file)
exit 0
