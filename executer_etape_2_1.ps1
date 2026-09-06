# Script d'exécution pour etape_2_1_contrat_p1.py
# Créé automatiquement

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "EXECUTION DE L'ETAPE 2.1 - CONTRATS P1" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Vérifier que le fichier Python existe
if (-not (Test-Path ".\etape_2_1_contrat_p1.py")) {
    Write-Host "ERREUR: Fichier etape_2_1_contrat_p1.py non trouve !" -ForegroundColor Red
    exit 1
}

# Exécuter le script Python
Write-Host "Execution du script Python..." -ForegroundColor Yellow
python .\etape_2_1_contrat_p1.py --self-test

# Vérifier le résultat
if ($LASTEXITCODE -eq 0) {
    Write-Host ""
    Write-Host "SUCCES - Le script s'est execute correctement" -ForegroundColor Green
} else {
    Write-Host ""
    Write-Host "ECHEC - Le script a rencontre une erreur (code: $LASTEXITCODE)" -ForegroundColor Red
}

# Optionnel: Rechercher les fichiers catalogue
Write-Host ""
Write-Host "Recherche des fichiers catalogue..." -ForegroundColor Yellow
if (Test-Path ".\contrats_p1") {
    $files = Get-ChildItem -Path ".\contrats_p1" -Recurse -File -Filter "catalogue_p1_v2.0.0*"
    if ($files) {
        Write-Host "Fichiers trouves :" -ForegroundColor Green
        $files | ForEach-Object { Write-Host "  - $($_.Name)" -ForegroundColor White }
    } else {
        Write-Host "Aucun fichier catalogue trouve" -ForegroundColor Gray
    }
} else {
    Write-Host "Dossier 'contrats_p1' non trouve" -ForegroundColor Gray
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "FIN DE L'EXECUTION" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
