# ops/qualify.ps1 - calculateur de qualification. Aucune note saisie a la main. v1.2.0
$ErrorActionPreference = "Stop"
$racine = Split-Path $PSScriptRoot -Parent
$sc = Get-Content (Join-Path $racine "scorecard.json") -Raw | ConvertFrom-Json
$somme = ($sc.domaines | Measure-Object -Property poids -Sum).Sum
if ($somme -ne 100) { Write-Output "CONFIG INVALIDE : poids = $somme (attendu 100)"; exit 3 }
foreach ($fatal in $sc.court_circuit_fatal) {
  if ($fatal.declenche) { Write-Output "NON QUALIFIE : $($fatal.id)"; exit 2 } }
# INV-1 ports : aucune publication 0.0.0.0 non justifiee
$exposes = @()
docker ps --format "{{.Names}} {{.Ports}}" | Select-String "0\.0\.0\.0" | ForEach-Object {
  $exposes += ($_.Line -split " ")[0] }
$exceptions = @($sc.ports_exposes_justifies) | Where-Object { $_ }
$viol = @($exposes | Where-Object { $_ -notin $exceptions })
if ($viol.Count -gt 0) { Write-Output "AUDIT BLOQUE [INV-1 ports] : $($viol -join ', ')"; exit 4 }
# INV-2 secrets : aucun credential dans les fichiers suivis (hors ce script)
Set-Location $racine
$suivis = git ls-files | Where-Object { $_ -ne "ops/qualify.ps1" }
$touches = @()
foreach ($fich in $suivis) {
  if (Select-String -Path $fich -Pattern "PASSWORD\s*[:=]|://[^/\s]+:[^@\s]+@" -Quiet -ErrorAction SilentlyContinue) { $touches += $fich } }
$exc2 = @($sc.secrets_justifies) | Where-Object { $_ }
$viol2 = @($touches | Where-Object { $_ -notin $exc2 })
if ($viol2.Count -gt 0) { Write-Output "AUDIT BLOQUE [INV-2 secrets versionnes] : $($viol2 -join ', ')"; exit 5 }
# INV-3 fraicheur : retard collecte <= 15 min
$retard = [decimal](docker exec tapo_postgres psql -U tapo -d tapo -t -A -c "SELECT ROUND(EXTRACT(EPOCH FROM now() - MAX(ts))/60,1) FROM shelly_minute;")
if ($retard -gt 15) { Write-Output "AUDIT BLOQUE [INV-3 fraicheur] : retard $retard min (seuil 15)"; exit 6 }
# INV-4 push : pas plus de 20 commits non pousses
$avance = [int](git rev-list --count "@{u}..HEAD" 2>$null)
if ($avance -gt 20) { Write-Output "AUDIT BLOQUE [INV-4 push] : $avance commits non pousses (seuil 20)"; exit 7 }
# --- calcul de note (inchange v1.0) ---
$bloques = @()
foreach ($d in $sc.domaines) {
  if ($d.points -gt $d.poids) { Write-Output "CONFIG INVALIDE : $($d.nom)"; exit 3 }
  if ($d.points -gt 0 -and $d.preuve -and -not (Test-Path (Join-Path $racine $d.preuve))) { $bloques += $d.nom } }
if ($bloques.Count -gt 0) { Write-Output "AUDIT BLOQUE : preuves absentes -> $($bloques -join ', ')"; exit 4 }
$brut = [decimal](($sc.domaines | Measure-Object -Property points -Sum).Sum)
$note = [math]::Round($brut / [decimal]10, 2)
$actifs = @()
foreach ($p in $sc.plafonds) {
  $leve = $false
  if ($p.preuve_levee) {
    $ch = Join-Path $racine $p.preuve_levee
    if ((Test-Path $ch) -and ((Get-FileHash $ch -Algorithm SHA256).Hash -eq $p.hash_attendu)) { $leve = $true } }
  if (-not $leve) { $actifs += $p } }
$plancher = if ($actifs.Count -gt 0) { ($actifs | Measure-Object -Property plafond -Minimum).Minimum } else { [decimal]10 }
$finale = [math]::Min($note, [decimal]$plancher)
$rapport = @("# SCORECARD_FINAL - qualify v1.2.0 - $(Get-Date -Format u)",
  "Invariants : ports OK, secrets OK, fraicheur $retard min, push $avance commits",
  "Score brut : $brut/100 -> $note/10",
  "Plafonds ACTIFS : $(($actifs | ForEach-Object { $_.id + '(' + $_.plafond + ')' }) -join ' ')",
  "NOTE FINALE : $finale/10")
$rapport | Set-Content (Join-Path $racine "SCORECARD_FINAL.md") -Encoding ASCII
$rapport | Write-Output
if ($finale -gt [decimal]9.0) { Write-Output "VERDICT : PRE-QUALIFIE > 9/10"; exit 0 }
else { Write-Output "VERDICT : NON QUALIFIE - $finale/10"; exit 1 }
