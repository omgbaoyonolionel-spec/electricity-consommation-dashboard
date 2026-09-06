param(
    [string]$Catalogue = "",
    [string]$ApprovedBy = "",
    [string]$ApprovalReference = "",
    [switch]$RegisterDatabase,
    [switch]$AuditDatabase
)

$ErrorActionPreference = "Stop"
$ProjectDir = "C:\Users\omgba.oyono.lionel\Desktop\CAPACITES\electricity-consommation-dashboard"
$InventoryRoot = "C:\Users\omgba.oyono.lionel\Desktop\SHELLY\shelly_inventory"
$Tool = Join-Path $ProjectDir "etape_2_1_contrat_p1.py"

if (-not (Test-Path $Tool)) {
    throw "Fichier absent : $Tool"
}

if (-not $Catalogue) {
    $Candidate = Get-ChildItem $InventoryRoot -Recurse -File `
        -Filter "03_04_catalogue_variables_classees.csv" |
        Sort-Object LastWriteTimeUtc -Descending |
        Select-Object -First 1
    if (-not $Candidate) {
        throw "Catalogue introuvable sous $InventoryRoot"
    }
    $Catalogue = $Candidate.FullName
}

Set-Location $ProjectDir
python .\etape_2_1_contrat_p1.py --self-test
if ($LASTEXITCODE -ne 0) { throw "Échec de l'auto-test" }

$Arguments = @(
    ".\etape_2_1_contrat_p1.py",
    "--catalog", $Catalogue,
    "--output-dir", ".\contrats_p1",
    "--device-id", "shellypro3em63-a4f00fccaf68",
    "--firmware", "1.4.0",
    "--contract-version", "2.0.0",
    "--expected-count", "23"
)

if ($ApprovedBy -or $ApprovalReference) {
    if (-not ($ApprovedBy -and $ApprovalReference)) {
        throw "ApprovedBy et ApprovalReference doivent être fournis ensemble"
    }
    $Arguments += @("--approved-by", $ApprovedBy, "--approval-reference", $ApprovalReference)
}

if ($RegisterDatabase -or $AuditDatabase) {
    $Dsn = docker inspect tapo_collector --format '{{range .Config.Env}}{{println .}}{{end}}' |
        Where-Object { $_ -like 'PG_DSN=*' } |
        Select-Object -First 1
    if (-not $Dsn) { throw "PG_DSN introuvable dans tapo_collector" }
    $env:PG_DSN = $Dsn.Substring(7)
}

if ($RegisterDatabase) { $Arguments += "--register-db" }
if ($AuditDatabase) { $Arguments += "--audit-db" }

try {
    & python @Arguments
    $ExitCode = $LASTEXITCODE
}
finally {
    Remove-Item Env:PG_DSN -ErrorAction SilentlyContinue
}

if ($ExitCode -ne 0) {
    throw "Étape 2.1 non conforme. Consultez le rapport JSON. Code=$ExitCode"
}

Write-Host "`nÉTAPE 2.1 : CONTRÔLES RÉUSSIS" -ForegroundColor Green
Get-ChildItem .\contrats_p1 -Recurse -File -Filter "catalogue_p1_v2.0.0*" |
    Select-Object FullName, Length, LastWriteTime
