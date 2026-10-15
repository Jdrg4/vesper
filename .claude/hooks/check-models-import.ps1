# Hook PostToolUse — Integridad de Alembic env.py
# Se dispara al crear/editar un src/**/models.py. Verifica que el modulo
# este importado en vesper-backend/alembic/env.py; si no, inyecta un
# recordatorio en el contexto (sin bloquear). Salida silenciosa si ya
# esta registrado o si el archivo editado no es un models.py.

$raw = [Console]::In.ReadToEnd()
try { $data = $raw | ConvertFrom-Json } catch { exit 0 }

$path = $data.tool_input.file_path
if (-not $path) { exit 0 }

# Normaliza separadores y exige que sea un models.py bajo src/
$norm = $path -replace '\\', '/'
if ($norm -notmatch 'src/.+/models\.py$') { exit 0 }

# Deriva el modulo punteado: .../src/review_jobs/models.py -> src.review_jobs.models
$rel = $norm.Substring($norm.IndexOf('src/'))
$module = ($rel -replace '\.py$', '') -replace '/', '.'

# Localiza env.py relativo a la raiz del repo (este script vive en .claude/hooks/)
$envPath = Join-Path $PSScriptRoot '..\..\vesper-backend\alembic\env.py'
if (Test-Path $envPath) {
    $envText = Get-Content $envPath -Raw
    if ($envText -match [regex]::Escape("import $module")) { exit 0 }  # ya registrado
}

$msg = "Alembic: el modulo '$module' NO esta importado en vesper-backend/alembic/env.py. " +
       "Agrega 'import $module  # noqa' junto a los demas imports de modelos, o " +
       "'alembic revision --autogenerate' ignorara estas tablas silenciosamente."

$out = @{
    hookSpecificOutput = @{
        hookEventName     = 'PostToolUse'
        additionalContext = $msg
    }
} | ConvertTo-Json -Compress

Write-Output $out
exit 0
