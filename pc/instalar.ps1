# Registra la tarea diaria en el Programador de tareas de Windows (una sola vez).
# Corre a las 14:00 (SEPA publica cerca de las 13:20) y, si la PC estaba apagada,
# apenas se prende. Se puede repetir sin problema: reemplaza la tarea.
$script = Join-Path $PSScriptRoot "actualizar.ps1"
$accion = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$script`""
$disparadores = @(
    (New-ScheduledTaskTrigger -Daily -At 14:00),
    (New-ScheduledTaskTrigger -Daily -At 18:30)
)
$opciones = New-ScheduledTaskSettingsSet -StartWhenAvailable -RunOnlyIfNetworkAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Hours 1)
Register-ScheduledTask -TaskName "Piqo - precios del dia" -Action $accion `
    -Trigger $disparadores -Settings $opciones -Force | Out-Null
Write-Host "Listo: la tarea 'Piqo - precios del dia' corre a las 14:00 y 18:30."
Write-Host "Para probarla ya: Start-ScheduledTask -TaskName 'Piqo - precios del dia'"
