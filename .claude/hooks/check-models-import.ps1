# Hook multi-agente (Claude Code / Codex / Antigravity) — Integridad de Alembic env.py
# - En Claude Code / Codex (PostToolUse Write|Edit): recibe $data.tool_input.file_path
#   y si es un src/**/models.py no importado en alembic/env.py, inyecta additionalContext.
# - En Antigravity (PreToolUse run_command / PostToolUse write_to_file|replace_file_content):
#   recibe $data.toolCall y valida que todos los src/**/models.py esten importados en
#   vesper-backend/alembic/env.py antes de correr `alembic revision`.

$raw = [Console]::In.ReadToEnd()
try { $data = $raw | ConvertFrom-Json } catch { exit 0 }

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$envPath = Join-Path $repoRoot 'vesper-backend\alembic\env.py'
if (-not (Test-Path $envPath)) { exit 0 }
$envText = Get-Content $envPath -Raw

# --- Modo Antigravity (payload con toolCall) ---
if ($null -ne $data.toolCall) {
    $cmd = $data.toolCall.args.CommandLine
    if ($cmd -and ($cmd -match 'alembic\s+revision')) {
        $srcRoot = Join-Path $repoRoot 'vesper-backend\src'
        $missing = @()
        if (Test-Path $srcRoot) {
            Get-ChildItem -Path $srcRoot -Filter 'models.py' -Recurse | ForEach-Object {
                $norm = $_.FullName -replace '\\', '/'
                $rel = $norm.Substring($norm.IndexOf('src/'))
                $mod = ($rel -replace '\.py$', '') -replace '/', '.'
                if ($envText -notmatch [regex]::Escape("import $mod")) {
                    $missing += $mod
                }
            }
        }
        if ($missing.Count -gt 0) {
            $mods = $missing -join ', '
            $msg = "Alembic: los modulos [$mods] NO estan importados en vesper-backend/alembic/env.py. " +
                   "Agrega 'import <modulo>  # noqa' antes de correr 'alembic revision --autogenerate'."
            Write-Output (@{ decision = 'deny'; reason = $msg } | ConvertTo-Json -Compress)
            exit 0
        }
        Write-Output (@{ decision = 'allow' } | ConvertTo-Json -Compress)
        exit 0
    }
    Write-Output (@{ decision = 'allow' } | ConvertTo-Json -Compress)
    exit 0
}

# --- Modo Claude Code / Codex (payload con tool_input.file_path) ---
$path = $data.tool_input.file_path
if (-not $path) { exit 0 }

$norm = $path -replace '\\', '/'
if ($norm -notmatch 'src/.+/models\.py$') { exit 0 }

$rel = $norm.Substring($norm.IndexOf('src/'))
$module = ($rel -replace '\.py$', '') -replace '/', '.'

if ($envText -match [regex]::Escape("import $module")) { exit 0 }

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
