# ops/qualify.ps1 - calculateur de qualification. Aucune note saisie a la main. v1.1.0
$ErrorActionPreference = "Stop"
$racine = Split-Path $PSScriptRoot -Parent
$sc = Get-Content (Join-Path $racine "scorecard.json") -Raw | ConvertFrom-Json
$somme = ($sc.domaines | Measure-Object -Property poids -Sum).Sum
if ($somme -ne 100) { Write-Output "CONFIG INVALIDE : poids = $somme (attendu 100)"; exit 3 }
foreach ($fatal in $sc.court_circuit_fatal) {
  if ($fatal.declenche) { Write-Output "NON QUALIFIE : $($fatal.id)"; exit 2 } }
# Invariant S2 : aucun port publie sur 0.0.0.0 (exceptions justifiees dans scorecard.json)
$exposes = @()
docker ps --format "{{.Names}} {{.Ports}}" | Select-String "0\.0\.0\.0" | ForEach-Object {
  $exposes += ($_.Line -split " ")[0] }
$exceptions = @($sc.ports_exposes_justifies) | Where-Object { $_ }
$violations = @($exposes | Where-Object { $_ -notin $exceptions })
if ($violations.Count -gt 0) {
  Write-Output "AUDIT BLOQUE : ports publies sur 0.0.0.0 sans justification -> $($violations -join ', ')"; exit 4 }
$bloques = @()
foreach ($d in $sc.domaines) {
  if ($d.points -gt $d.poids) { Write-Output "CONFIG INVALIDE : $($d.nom) points > poids"; exit 3 }
  if ($d.points -gt 0 -and $d.preuve -and -not (Test-Path (Join-Path $racine $d.preuve))) { $bloques += $d.nom } }
if ($bloques.Count -gt 0) { Write-Output "AUDIT BLOQUE : preuves absentes -> $($bloques -join ', ')"; exit 4 }
$brut = [decimal](($sc.domaines | Measure-Object -Property points -Sum).Sum)
$note = [math]::Round($brut / [decimal]10, 2)
$actifs = @()
foreach ($p in $sc.plafonds) {
  $leve = $false
  if ($p.preuve_levee) {
    $chemin = Join-Path $racine $p.preuve_levee
    if ((Test-Path $chemin) -and ((Get-FileHash $chemin -Algorithm SHA256).Hash -eq $p.hash_attendu)) { $leve = $true } }
  if (-not $leve) { $actifs += $p } }
$plancher = if ($actifs.Count -gt 0) { ($actifs | Measure-Object -Property plafond -Minimum).Minimum } else { [decimal]10 }
$finale = [math]::Min($note, [decimal]$plancher)
$rapport = @("# SCORECARD_FINAL - genere par ops/qualify.ps1 v1.1.0 le $(Get-Date -Format u)",
  "Fenetre : $($sc.fenetre_auditee.debut) -> $($sc.fenetre_auditee.fin) - appareil $($sc.fenetre_auditee.appareil) - commit $($sc.fenetre_auditee.commit)",
  "Invariant ports : 0 exposition non justifiee (verifie sur docker ps)",
  "Score brut : $brut/100 -> $note/10",
  "Plafonds ACTIFS : $(($actifs | ForEach-Object { $_.id + '(' + $_.plafond + ')' }) -join ' ')",
  "NOTE FINALE : $finale/10")
$rapport | Set-Content (Join-Path $racine "SCORECARD_FINAL.md") -Encoding ASCII
$rapport | Write-Output
if ($finale -gt [decimal]9.0) { Write-Output "VERDICT : PRE-QUALIFIE > 9/10 (observation SLA 30 j non achevee)"; exit 0 }
else { Write-Output "VERDICT : NON QUALIFIE - $finale/10"; exit 1 }
