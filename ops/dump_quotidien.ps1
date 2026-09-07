# DUMP QUOTIDIEN SHELLY - 03:00 par le Planificateur. v1.0.0
$d = Get-Date -Format "yyyyMMdd"
$rep = "C:\Users\omgba.oyono.lionel\Desktop\SHELLY\backups"
$fich = "$rep\tapo_quotidien_$d.dump"
docker exec tapo_postgres pg_dump -U tapo -d tapo -Fc -f /tmp/dq.dump 2>$null
docker cp tapo_postgres:/tmp/dq.dump $fich 2>$null
if (Test-Path $fich) {
    "$((Get-FileHash $fich -Algorithm SHA256).Hash)  tapo_quotidien_$d.dump" | Set-Content "$fich.sha256"
    Add-Content "$rep\dump_quotidien.log" "$(Get-Date -Format u) OK $([math]::Round((Get-Item $fich).Length/1MB,1)) Mo"
    Get-ChildItem $rep -Filter "tapo_quotidien_*.dump" | Sort-Object Name -Descending | Select-Object -Skip 7 | ForEach-Object { Remove-Item $_.FullName, "$($_.FullName).sha256" -ErrorAction SilentlyContinue }
} else {
    Add-Content "$rep\dump_quotidien.log" "$(Get-Date -Format u) ECHEC"
    Set-Content "$env:USERPROFILE\Desktop\ALERTE_SHELLY.txt" "$(Get-Date -Format u) - DUMP QUOTIDIEN EN ECHEC"
}
