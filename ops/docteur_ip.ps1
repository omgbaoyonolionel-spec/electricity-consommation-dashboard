# DOCTEUR IP SHELLY - execute toutes les 5 min par le Planificateur. v1.0.0
# Verifie que l appareil repond a l IP du .env ; sinon cherche <prefixe_local>.134,
# corrige le .env, recree les collecteurs, journalise. Alerte Bureau si echec total.
$repo    = "C:\Users\omgba.oyono.lionel\Desktop\CAPACITES\electricity-consommation-dashboard"
$journal = "C:\Users\omgba.oyono.lionel\Desktop\SHELLY\docteur_ip.log"
$alerte  = "$env:USERPROFILE\Desktop\ALERTE_SHELLY.txt"
$mac     = "a4f00fccaf68"
$horo    = Get-Date -Format "yyyy-MM-dd HH:mm:ss"

function Test-Shelly($ip) {
    try {
        $r = & curl.exe --noproxy "*" -s -m 5 "http://$ip/rpc/Shelly.GetDeviceInfo" 2>$null
        return ($r -match $mac)
    } catch { return $false }
}

$envPath = Join-Path $repo ".env"
$ipActuelle = ((Get-Content $envPath | Select-String "^SHELLY_IP=").Line -split "=")[1].Trim()

if (Test-Shelly $ipActuelle) {
    if (Test-Path $alerte) { Remove-Item $alerte -Force }
    Add-Content $journal "$horo OK $ipActuelle"
    exit 0
}

# IP morte : chercher <prefixe>.134 sur les sous-reseaux locaux
$candidates = (Get-NetIPAddress -AddressFamily IPv4 |
    Where-Object { $_.IPAddress -notmatch "^(127|172\.30)" } |
    ForEach-Object { ($_.IPAddress -split "\.")[0..2] -join "." }) |
    Sort-Object -Unique | ForEach-Object { "$_.134" }

foreach ($ip in $candidates) {
    if (Test-Shelly $ip) {
        (Get-Content $envPath -Raw) -replace "SHELLY_IP=.*", "SHELLY_IP=$ip" |
            Set-Content $envPath -NoNewline
        Set-Location $repo
        docker compose up -d --force-recreate shelly_collector shelly_history shelly_p1 shelly_sentinelle 2>&1 | Out-Null
        Add-Content $journal "$horo ROTATION $ipActuelle -> $ip : collecteurs recrees"
        if (Test-Path $alerte) { Remove-Item $alerte -Force }
        exit 0
    }
}

Add-Content $journal "$horo ECHEC : $ipActuelle morte, aucun .134 local ne repond"
Set-Content $alerte "$horo - Shelly injoignable ($ipActuelle morte, aucun .134 trouve). Verifier hotspot / alimentation / ecran du telephone."
