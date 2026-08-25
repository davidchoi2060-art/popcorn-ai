<#
.SYNOPSIS
    팝콘PC AI — 로컬 API 서버 + 현황판 감시자를 "로그온 시" 작업 스케줄러에 등록/해제한다.

.DESCRIPTION
    두 작업을 등록한다(작업 폴더 \PopcornAI\):

      PopcornAI-Api          uvicorn api.main:app --port 8000
                              명령은 E:\DEV\.claude\launch.json 의 "api" 설정을 **그대로**
                              옮긴 것이다 — 여기서 새로 짓지 않는다(정본은 그 파일).
      PopcornAI-DashWatch    scripts\dash_watch.py --service
                              하트비트 전용 모드 — 큐를 소비(읽음 처리)하지 않는다.
                              세션이 스스로 띄우는 알림 모드(인자 없음, Monitor 로 기동)와는
                              다른 프로세스다 — 자세한 이유는 dash_watch.py 머리 주석
                              "2026-08-25 — 상시 기동과 세션 알림이 부딪히는 문제" 참고.

    둘 다:
      트리거    로그온 시(-AtLogOn, 현재 사용자) — 부팅 시(OnStart)가 아니다. 이유는
                아래 "왜 로그온인가" 참고.
      실행      pythonw.exe(콘솔 창 없음) — python.exe 가 아니다.
      실패 시   1분 간격 최대 3회 재시작(-RestartCount 3 -RestartInterval 1분).
      단일 실행 -MultipleInstances IgnoreNew — 작업 스케줄러 자신이 같은 작업을 중복
                기동하지 않는다. dash_watch.py --service 는 **그와 별개로** 자체 PID
                잠금도 갖고 있다(사람이 수동으로 두 번 띄우는 경우까지 막기 위해서다 —
                Task Scheduler 의 이 옵션은 "같은 작업"만 막지, 수동 실행은 못 막는다).

    **이 스크립트는 실행해야만 등록된다 — 읽기만 해서는 아무것도 바뀌지 않는다.**
    무엇이 등록될지만 보려면 `-WhatIf` 를 붙인다(실제로 만들지 않는다).

.PARAMETER Unregister
    등록 대신 두 작업을 작업 스케줄러에서 제거한다. 프로세스가 지금 떠 있어도
    직접 죽이지 않는다 — "다음 로그온부터 자동으로 안 뜬다"는 뜻이다. 지금 떠 있는
    프로세스를 멈추려면 작업 관리자에서 직접 종료하거나, dash_watch.py 는 창을 닫는
    쪽을 권장한다(팀 메모 "감시자는 PC 에 한 벌만").

.PARAMETER WhatIf
    실제로 등록/해제하지 않고 무엇을 할지만 출력한다(PowerShell 공용 스위치).

.EXAMPLE
    무엇이 등록될지만 미리 본다(아무것도 안 바뀐다):
        powershell -ExecutionPolicy Bypass -File E:\DEV\popcorn-ai\scripts\autostart.ps1 -WhatIf

.EXAMPLE
    실제로 등록한다:
        powershell -ExecutionPolicy Bypass -File E:\DEV\popcorn-ai\scripts\autostart.ps1

.EXAMPLE
    등록을 해제한다(원복):
        powershell -ExecutionPolicy Bypass -File E:\DEV\popcorn-ai\scripts\autostart.ps1 -Unregister

.NOTES
    왜 로그온인가(부팅이 아니라) — 서버·감시자가 `.venv`·`.env`·E: 드라이브 등 **사용자
    계정 권한으로 매핑된 자원**을 읽는다. 부팅 시(OnStart) 트리거는 기본적으로 SYSTEM
    계정으로 돌아 이 자원에 접근하지 못하거나 다른 사용자 프로필을 볼 수 있고, SYSTEM 이
    아닌 "이 사용자"로 부팅 시 돌리려면 Windows 비밀번호를 작업에 저장해야 한다(S4U 로
    피할 수도 있지만 그러면 로그온 전에도 뜨려는 목적 자체가 흐려진다 — 사용자 세션이
    없으면 매핑 드라이브·프로필이 없을 수 있다). 로그온 트리거는 **비밀번호 저장 없이**
    "이 사용자"로 등록할 수 있고(LogonType=Interactive), 일반적인 개인 PC에서는 로그온이
    곧 "PC 켰다"와 사실상 같은 순간이라 요구사항("PC 켤 때 자동으로")을 충분히 만족한다.

    관리자 권한 — 이 스크립트는 **현재 로그온한 사용자 자신**의 작업만 등록한다
    (RunLevel=Limited, 관리자 권한 요구 안 함). 일반 PowerShell 창에서 실행하면 된다.
    다만 회사·정책상 제한된 계정이면 Windows 가 그래도 거부할 수 있다 — 그 경우
    "관리자 권한으로 실행"한 PowerShell 에서 다시 시도한다.

    비밀번호 — 이 스크립트도, 등록되는 작업도 ADMIN_PW 를 어디에도 적지 않는다.
    dash_watch.py 는 실행될 때 자기 스스로 `.env` 를 읽는다(정본 방식 그대로) — 작업
    스케줄러 등록 정보에는 프로그램 경로와 인자만 들어간다.
#>
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [switch]$Unregister
)

$ErrorActionPreference = "Stop"

# ── 경로 — E:\DEV\.claude\launch.json 의 "api" 설정을 그대로 옮긴다(정본, 새로 짓지 않는다) ──
#   runtimeExecutable: "popcorn-ai/.venv/Scripts/python"  (E:\DEV 기준 상대경로)
#   runtimeArgs:       -m uvicorn --app-dir popcorn-ai api.main:app --port 8000
$DevRoot   = "E:\DEV"
$ProjRoot  = Join-Path $DevRoot "popcorn-ai"
$VenvPy    = Join-Path $ProjRoot ".venv\Scripts\python.exe"
$VenvPyW   = Join-Path $ProjRoot ".venv\Scripts\pythonw.exe"
$DashWatch = Join-Path $ProjRoot "scripts\dash_watch.py"

$TaskPath  = "\PopcornAI\"
$TaskApi   = "PopcornAI-Api"
$TaskWatch = "PopcornAI-DashWatch"

function Assert-Paths {
    foreach ($p in @($VenvPy, $VenvPyW, $DashWatch)) {
        if (-not (Test-Path -LiteralPath $p)) {
            throw "경로 없음: $p — 이 PC 구성이 스크립트가 가정한 것과 다르다. 등록하지 않는다."
        }
    }
}

function Register-Tasks {
    Assert-Paths

    $apiAction = New-ScheduledTaskAction -Execute $VenvPyW `
        -Argument "-m uvicorn --app-dir popcorn-ai api.main:app --port 8000" `
        -WorkingDirectory $DevRoot

    $watchAction = New-ScheduledTaskAction -Execute $VenvPyW `
        -Argument "`"$DashWatch`" --service" `
        -WorkingDirectory $ProjRoot

    $userId = "$env:USERDOMAIN\$env:USERNAME"
    $trigger = New-ScheduledTaskTrigger -AtLogOn -User $userId

    $settings = New-ScheduledTaskSettingsSet `
        -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable `
        -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) `
        -ExecutionTimeLimit ([TimeSpan]::Zero) `
        -MultipleInstances IgnoreNew

    $principal = New-ScheduledTaskPrincipal -UserId $userId -LogonType Interactive -RunLevel Limited

    $defs = @(
        @{ Name = $TaskApi;   Action = $apiAction;   Desc = "팝콘PC AI 로컬 API 서버(uvicorn :8000, launch.json 'api' 그대로) — 로그온 시 자동 시작" }
        @{ Name = $TaskWatch; Action = $watchAction; Desc = "팝콘PC AI 현황판 감시자(--service, 하트비트 전용·큐 미소비) — 로그온 시 자동 시작" }
    )

    foreach ($t in $defs) {
        $existing = Get-ScheduledTask -TaskName $t.Name -TaskPath $TaskPath -ErrorAction SilentlyContinue
        if ($existing) {
            if ($PSCmdlet.ShouldProcess("$TaskPath$($t.Name)", "기존 작업 제거 후 재등록")) {
                Unregister-ScheduledTask -TaskName $t.Name -TaskPath $TaskPath -Confirm:$false
            }
        }
        if ($PSCmdlet.ShouldProcess("$TaskPath$($t.Name)", "작업 스케줄러에 등록 (로그온 트리거)")) {
            Register-ScheduledTask -TaskName $t.Name -TaskPath $TaskPath `
                -Action $t.Action -Trigger $trigger -Settings $settings -Principal $principal `
                -Description $t.Desc | Out-Null
            Write-Output "등록됨: $TaskPath$($t.Name)"
        }
    }

    Write-Output ""
    Write-Output "다음 로그온부터 자동 시작한다. 재로그온하지 않고 지금 바로 시작하려면:"
    Write-Output "  Start-ScheduledTask -TaskPath '$TaskPath' -TaskName '$TaskApi'"
    Write-Output "  Start-ScheduledTask -TaskPath '$TaskPath' -TaskName '$TaskWatch'"
    Write-Output "상태 확인:"
    Write-Output "  Get-ScheduledTask -TaskPath '$TaskPath' | Get-ScheduledTaskInfo"
}

function Unregister-Tasks {
    foreach ($name in @($TaskApi, $TaskWatch)) {
        $existing = Get-ScheduledTask -TaskName $name -TaskPath $TaskPath -ErrorAction SilentlyContinue
        if ($existing) {
            if ($PSCmdlet.ShouldProcess("$TaskPath$name", "작업 스케줄러에서 제거")) {
                Unregister-ScheduledTask -TaskName $name -TaskPath $TaskPath -Confirm:$false
                Write-Output "제거됨: $TaskPath$name"
            }
        } else {
            Write-Output "이미 없음: $TaskPath$name"
        }
    }
    Write-Output ""
    Write-Output "지금 떠 있는 프로세스는 그대로다(작업 등록만 해제했다) — 멈추려면 직접 종료한다."
}

if ($Unregister) {
    Unregister-Tasks
} else {
    Register-Tasks
}
