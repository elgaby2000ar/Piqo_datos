# Arma el paquete de precios de hoy y lo sube a la rama `paquete` de Piqo_datos.
# Lo corre el Programador de tareas de Windows (ver pc/instalar.ps1). Si hoy ya está
# publicado, no hace nada. Registro en pc\actualizar.log.
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$log = Join-Path $PSScriptRoot "actualizar.log"
function Anotar($texto) { "$(Get-Date -Format s)  $texto" | Tee-Object -FilePath $log -Append }

try {
    Set-Location $repo
    git pull --quiet origin main
    $remoto = git remote get-url origin
    $sitio = Join-Path $env:TEMP "piqo_sitio"
    if (Test-Path $sitio) { Remove-Item -Recurse -Force $sitio }

    Push-Location (Join-Path $repo "constructor")
    python -m pip install --quiet --disable-pip-version-check "httpx>=0.27"
    python scripts/armar_paquete.py --salida $sitio | Out-Null
    $codigo = $LASTEXITCODE
    Pop-Location
    if ($codigo -ne 0) { Anotar "armar_paquete terminó con código $codigo"; exit $codigo }

    $nuevo = (Get-Content (Join-Path $sitio "v1/manifiesto.json") | ConvertFrom-Json)
    try {
        $publicado = Invoke-RestMethod "https://elgaby2000ar.github.io/Piqo_datos/v1/manifiesto.json" -TimeoutSec 20
        if ($publicado.fecha -eq $nuevo.fecha) { Anotar "Ya estaba publicado el $($nuevo.fecha)"; exit 0 }
    } catch { }

    # Rama sin historia: un solo commit que reemplaza al de ayer. Lleva el workflow
    # para que el push lo dispare (GitHub lo busca en la rama que llega).
    Copy-Item -Recurse (Join-Path $repo ".github") (Join-Path $sitio ".github")
    Push-Location $sitio
    git init --quiet
    git checkout --quiet -b paquete
    git add -A
    git -c user.name="Piqo PC" -c user.email="piqo@localhost" commit --quiet -m "Paquete $($nuevo.fecha)"
    git push --quiet --force $remoto paquete
    Pop-Location
    Anotar "Publicado $($nuevo.fecha): $($nuevo.productos) productos, $($nuevo.precios) precios"
} catch {
    Anotar "Error: $_"
    exit 1
}
