<#
.SYNOPSIS
  Verifies the INS-2 development stack is actually working, not merely running.

.DESCRIPTION
  A container being "up" proves nothing. This checks behaviour:
    - pgvector extension is installed
    - the audit role can INSERT but CANNOT UPDATE  (the basis of gate 2)
    - Redis responds
    - Qdrant is ready
    - SpiceDB is serving
    - Langfuse answers on 3000
    - Ollama returns an embedding of exactly EMBEDDING_DIMENSION

.EXAMPLE
  .\scripts\smoke-stack.ps1
#>
[CmdletBinding()]
param()

$ErrorActionPreference = 'Continue'
$script:Failures = 0

function Test-Step {
    param([string]$Name, [scriptblock]$Check)
    Write-Host ("  {0,-44}" -f $Name) -NoNewline
    try {
        $detail = & $Check
        Write-Host "PASS" -ForegroundColor Green -NoNewline
        if ($detail) { Write-Host "  $detail" -ForegroundColor DarkGray } else { Write-Host "" }
    } catch {
        Write-Host "FAIL" -ForegroundColor Red -NoNewline
        Write-Host "  $($_.Exception.Message)" -ForegroundColor DarkYellow
        $script:Failures++
    }
}

# --- load .env -------------------------------------------------------------
$envPath = Join-Path $PSScriptRoot '..\.env'
if (-not (Test-Path $envPath)) { throw ".env not found. Copy-Item .env.example .env first." }
$cfg = @{}
Get-Content $envPath | ForEach-Object {
    if ($_ -match '^\s*([A-Z0-9_]+)\s*=\s*(.*)$') { $cfg[$Matches[1]] = $Matches[2].Trim() }
}
$pgUser = if ($cfg.POSTGRES_USER) { $cfg.POSTGRES_USER } else { 'insight' }
$pgDb   = if ($cfg.POSTGRES_DB)   { $cfg.POSTGRES_DB }   else { 'insight' }
$embModel = if ($cfg.EMBEDDING_MODEL) { $cfg.EMBEDDING_MODEL } else { 'nomic-embed-text' }
$embDim   = [int]($(if ($cfg.EMBEDDING_DIMENSION) { $cfg.EMBEDDING_DIMENSION } else { 768 }))
$auditUser = if ($cfg.POSTGRES_AUDIT_USER) { $cfg.POSTGRES_AUDIT_USER } else { 'insight_audit' }

Write-Host "`nInSight stack smoke test" -ForegroundColor Cyan
Write-Host "------------------------" -ForegroundColor DarkGray

# --- containers ------------------------------------------------------------
Write-Host "`nContainers" -ForegroundColor Cyan
foreach ($c in @('insight-postgres','insight-redis','insight-qdrant','insight-spicedb','insight-langfuse')) {
    Test-Step $c {
        $state = docker inspect -f '{{.State.Status}}' $c 2>$null
        if ($LASTEXITCODE -ne 0) { throw "not found" }
        if ($state -ne 'running') { throw "state=$state" }
        $state
    }
}

# --- postgres --------------------------------------------------------------
Write-Host "`nPostgres" -ForegroundColor Cyan

Test-Step "accepting connections" {
    docker exec insight-postgres pg_isready -U $pgUser -d $pgDb 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "pg_isready failed" }
}

Test-Step "pgvector extension installed" {
    $v = docker exec insight-postgres psql -U $pgUser -d $pgDb -tAc "SELECT extversion FROM pg_extension WHERE extname='vector'"
    if (-not $v) { throw "vector extension missing" }
    "v$($v.Trim())"
}

Test-Step "sidecar databases exist" {
    $dbs = docker exec insight-postgres psql -U $pgUser -d postgres -tAc "SELECT datname FROM pg_database WHERE datname IN ('spicedb','langfuse') ORDER BY datname"
    $found = ($dbs -split "`n" | Where-Object { $_.Trim() }) -join ','
    if ($found -notmatch 'langfuse' -or $found -notmatch 'spicedb') { throw "found: $found" }
    $found
}

Test-Step "audit role exists" {
    $r = docker exec insight-postgres psql -U $pgUser -d $pgDb -tAc "SELECT rolname FROM pg_roles WHERE rolname='$auditUser'"
    if (-not $r) { throw "role $auditUser missing" }
    $r.Trim()
}

Test-Step "audit role CANNOT update (gate 2 basis)" {
    docker exec insight-postgres psql -U $pgUser -d $pgDb -q -c `
        "CREATE TABLE IF NOT EXISTS _smoke_audit(id serial primary key, note text)" 2>&1 | Out-Null
    # grants were set via ALTER DEFAULT PRIVILEGES, so apply them to this new table
    docker exec insight-postgres psql -U $pgUser -d $pgDb -q -c `
        "GRANT SELECT, INSERT ON _smoke_audit TO $auditUser; GRANT USAGE ON SEQUENCE _smoke_audit_id_seq TO $auditUser" 2>&1 | Out-Null

    $ins = docker exec insight-postgres psql -U $auditUser -d $pgDb -tAc "INSERT INTO _smoke_audit(note) VALUES ('x') RETURNING id" 2>&1
    if ($LASTEXITCODE -ne 0) { throw "audit role could not INSERT: $ins" }

    $upd = docker exec insight-postgres psql -U $auditUser -d $pgDb -tAc "UPDATE _smoke_audit SET note='tampered'" 2>&1
    $updFailed = ($LASTEXITCODE -ne 0)

    $del = docker exec insight-postgres psql -U $auditUser -d $pgDb -tAc "DELETE FROM _smoke_audit" 2>&1
    $delFailed = ($LASTEXITCODE -ne 0)

    docker exec insight-postgres psql -U $pgUser -d $pgDb -q -c "DROP TABLE _smoke_audit" 2>&1 | Out-Null

    if (-not $updFailed) { throw "UPDATE SUCCEEDED - audit log is not tamper-proof" }
    if (-not $delFailed) { throw "DELETE SUCCEEDED - audit log is not tamper-proof" }
    "insert ok, update denied, delete denied"
}

# --- redis -----------------------------------------------------------------
Write-Host "`nRedis" -ForegroundColor Cyan
Test-Step "responds to PING" {
    $p = docker exec insight-redis redis-cli ping
    if ($p.Trim() -ne 'PONG') { throw "got '$p'" }
}
Test-Step "streams usable" {
    docker exec insight-redis redis-cli XADD _smoke '*' k v   | Out-Null
    $len = docker exec insight-redis redis-cli XLEN _smoke
    docker exec insight-redis redis-cli DEL _smoke            | Out-Null
    if ([int]$len.Trim() -lt 1) { throw "XLEN=$len" }
}

# --- qdrant / langfuse -----------------------------------------------------
Write-Host "`nHTTP services" -ForegroundColor Cyan
Test-Step "Qdrant ready (6333)" {
    $r = Invoke-WebRequest -Uri 'http://localhost:6333/readyz' -UseBasicParsing -TimeoutSec 10
    if ($r.StatusCode -ne 200) { throw "HTTP $($r.StatusCode)" }
}
Test-Step "Langfuse answering (3000)" {
    $r = Invoke-WebRequest -Uri 'http://localhost:3000/api/public/health' -UseBasicParsing -TimeoutSec 20
    if ($r.StatusCode -ne 200) { throw "HTTP $($r.StatusCode)" }
}
Test-Step "SpiceDB serving (50051)" {
    $t = Test-NetConnection -ComputerName localhost -Port 50051 -WarningAction SilentlyContinue
    if (-not $t.TcpTestSucceeded) { throw "port closed" }
}

# --- ollama ----------------------------------------------------------------
Write-Host "`nOllama (native, not containerised)" -ForegroundColor Cyan

Test-Step "API reachable (11434)" {
    $r = Invoke-RestMethod -Uri 'http://localhost:11434/api/tags' -TimeoutSec 15
    "$($r.models.Count) model(s)"
}

Test-Step "$embModel pulled" {
    $r = Invoke-RestMethod -Uri 'http://localhost:11434/api/tags' -TimeoutSec 15
    $names = $r.models | ForEach-Object { $_.name }
    if (-not ($names -match [regex]::Escape($embModel))) { throw "not pulled. names: $($names -join ', ')" }
}

Test-Step "embedding dimension == $embDim" {
    $body = @{ model = $embModel; prompt = 'quarterly revenue forecast for the board' } | ConvertTo-Json
    $r = Invoke-RestMethod -Uri 'http://localhost:11434/api/embeddings' -Method Post `
         -ContentType 'application/json' -Body $body -TimeoutSec 120
    $n = $r.embedding.Count
    if ($n -ne $embDim) { throw "model returned $n, .env says $embDim - fix EMBEDDING_DIMENSION before indexing anything" }
    "$n dims"
}

Test-Step "embeddings are deterministic" {
    $body = @{ model = $embModel; prompt = 'same text twice' } | ConvertTo-Json
    $a = (Invoke-RestMethod -Uri 'http://localhost:11434/api/embeddings' -Method Post -ContentType 'application/json' -Body $body -TimeoutSec 120).embedding
    $b = (Invoke-RestMethod -Uri 'http://localhost:11434/api/embeddings' -Method Post -ContentType 'application/json' -Body $body -TimeoutSec 120).embedding
    $drift = [Math]::Abs($a[0] - $b[0])
    if ($drift -gt 1e-6) { throw "drift $drift between identical inputs" }
}

Test-Step "generation responds" {
    $gen = if ($cfg.LITELLM_GENERATION_MODEL) { $cfg.LITELLM_GENERATION_MODEL -replace '^ollama/', '' } else { 'llama3.1:8b' }
    $body = @{ model = $gen; prompt = 'Reply with the single word: OK'; stream = $false } | ConvertTo-Json
    $r = Invoke-RestMethod -Uri 'http://localhost:11434/api/generate' -Method Post `
         -ContentType 'application/json' -Body $body -TimeoutSec 180
    if (-not $r.response) { throw "empty response" }
    "`"$($r.response.Trim() -replace '\s+',' ')`""
}

# --- summary ---------------------------------------------------------------
Write-Host ""
if ($script:Failures -eq 0) {
    Write-Host "All checks passed. Development stack is healthy." -ForegroundColor Green
    exit 0
} else {
    Write-Host "$($script:Failures) check(s) failed." -ForegroundColor Red
    exit 1
}
