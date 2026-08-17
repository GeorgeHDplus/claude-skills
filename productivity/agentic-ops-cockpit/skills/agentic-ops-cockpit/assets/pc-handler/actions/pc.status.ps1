# pc.status — Uptime, CPU-Last, RAM, aktiver User (read-only, idempotent).
param($Params, $Config)

$os = Get-CimInstance Win32_OperatingSystem
$uptime = (Get-Date) - $os.LastBootUpTime
$cpu = (Get-CimInstance Win32_Processor | Measure-Object -Property LoadPercentage -Average).Average
$totalGb = [math]::Round($os.TotalVisibleMemorySize / 1MB, 1)   # KB -> GB
$freeGb  = [math]::Round($os.FreePhysicalMemory / 1MB, 1)

@{
    status           = 'ok'
    uptime_hours     = [math]::Round($uptime.TotalHours, 1)
    cpu_load_percent = [int]$cpu
    ram_used_gb      = [math]::Round($totalGb - $freeGb, 1)
    ram_total_gb     = $totalGb
    active_user      = $env:USERNAME
}
