"""
Analyse de l'historique complet de la collecte Tapo.

Pipeline : chargement -> nettoyage (doublons double-flux, périodes dégradées)
-> qualité de collecte -> profils de puissance -> énergie journalière fiable
(via month_energy_wh) -> exports (PNG + Excel).

Prérequis :
    pip install pandas sqlalchemy psycopg2-binary matplotlib openpyxl
Exécution (conteneur postgres démarré) :
    python analyse_historique.py
"""
from pathlib import Path

import matplotlib
matplotlib.use("Agg")  # rendu fichier, pas de fenêtre
import matplotlib.pyplot as plt
import pandas as pd
from sqlalchemy import create_engine

# ---------------------------------------------------------------- paramètres
PG_URL = "postgresql+psycopg2://tapo:tapo_password@localhost:5432/tapo"
TZ = "Africa/Douala"
PAS_NOMINAL_S = 5          # cadence configurée (--loop)
SEUIL_DOUBLON_S = 3        # pas < 3 s = collision double-flux
SEUIL_TROU_S = 60          # pas > 60 s = interruption de collecte
OUT = Path("analyse_historique_out")
OUT.mkdir(exist_ok=True)

# ---------------------------------------------------------------- chargement
engine = create_engine(PG_URL)
df = pd.read_sql(
    "SELECT device_name, timestamp, current_power_mw, "
    "today_energy_wh, month_energy_wh, on_state "
    "FROM tapo_readings ORDER BY timestamp",
    engine,
    parse_dates=["timestamp"],
)
df["heure_locale"] = df["timestamp"].dt.tz_convert(TZ)
df["puissance_w"] = df["current_power_mw"] / 1000.0
print(f"Chargé : {len(df):,} lignes, "
      f"du {df['heure_locale'].min()} au {df['heure_locale'].max()}")

# ------------------------------------------------------- nettoyage qualité
df = df.sort_values(["device_name", "timestamp"]).reset_index(drop=True)
df["pas_s"] = (
    df.groupby("device_name")["timestamp"].diff().dt.total_seconds()
)

# 1) collisions du double-flux : on retire la ligne arrivée < 3 s après la
#    précédente (série fantôme entrelacée)
doublons = df["pas_s"] < SEUIL_DOUBLON_S
print(f"Collisions double-flux retirées : {doublons.sum():,}")
df_clean = df[~doublons].copy()
df_clean["pas_s"] = (
    df_clean.groupby("device_name")["timestamp"].diff().dt.total_seconds()
)

# 2) étiquette de qualité par lecture, pour pondérer les interprétations
def qualite(pas):
    if pd.isna(pas) or pas <= 3 * PAS_NOMINAL_S:
        return "nominale"
    if pas <= SEUIL_TROU_S:
        return "degradee"
    return "reprise_apres_trou"

df_clean["qualite"] = df_clean["pas_s"].map(qualite)

# --------------------------------------------- 1. qualité de la collecte
qual = (
    df_clean.assign(jour=df_clean["heure_locale"].dt.date)
    .groupby(["jour", "device_name"])
    .agg(lectures=("timestamp", "size"),
         pas_moyen_s=("pas_s", "mean"),
         trous=("pas_s", lambda s: (s > SEUIL_TROU_S).sum()))
    .round(1)
    .reset_index()
)
qual["couverture_pct"] = (
    100 * qual["lectures"] / (86400 / PAS_NOMINAL_S)
).round(1)

# ------------------------------------------------- 2. profils de puissance
stats_p = (
    df_clean.groupby("device_name")["puissance_w"]
    .describe(percentiles=[0.05, 0.25, 0.5, 0.75, 0.95])
    .round(1)
)

profil_h = (
    df_clean.assign(h=df_clean["heure_locale"].dt.hour)
    .groupby(["device_name", "h"])["puissance_w"]
    .mean()
    .unstack(0)
)

# ---------------------------------- 3. énergie journalière (month_energy_wh)
# monotone hors incidents -> delta max-min par jour local = énergie du jour
energie = (
    df_clean.assign(jour=df_clean["heure_locale"].dt.date)
    .groupby(["jour", "device_name"])["month_energy_wh"]
    .agg(lambda s: s.max() - s.min())
    .unstack()
)

# --------------------------------------------------------------- graphiques
fig, ax = plt.subplots(figsize=(12, 5))
for prise, g in df_clean.groupby("device_name"):
    ax.plot(g["heure_locale"], g["puissance_w"], lw=0.3, label=prise)
ax.set_title("Puissance instantanée — historique complet (nettoyé)")
ax.set_ylabel("W"); ax.legend()
fig.savefig(OUT / "01_puissance_historique.png", dpi=150,
            bbox_inches="tight")

fig, ax = plt.subplots(figsize=(10, 4))
profil_h.plot(ax=ax)
ax.set_title("Profil horaire moyen (heure locale)")
ax.set_xlabel("Heure"); ax.set_ylabel("W")
fig.savefig(OUT / "02_profil_horaire.png", dpi=150, bbox_inches="tight")

fig, ax = plt.subplots(figsize=(10, 4))
energie.plot(kind="bar", ax=ax)
ax.set_title("Énergie journalière (Wh, via month_energy_wh)")
fig.savefig(OUT / "03_energie_journaliere.png", dpi=150,
            bbox_inches="tight")

# ------------------------------------------------------------------- Excel
with pd.ExcelWriter(OUT / "synthese.xlsx") as xl:
    qual.to_excel(xl, "qualite_collecte", index=False)
    stats_p.to_excel(xl, "stats_puissance")
    profil_h.round(1).to_excel(xl, "profil_horaire")
    energie.to_excel(xl, "energie_journaliere")

print(f"\nRésultats dans {OUT}/ : 3 PNG + synthese.xlsx")
print("\n--- Qualité par jour ---\n", qual.to_string(index=False))
print("\n--- Stats puissance (W) ---\n", stats_p)