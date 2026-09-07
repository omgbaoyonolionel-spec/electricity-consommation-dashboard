#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
=============================================================================
ANALYSES STATISTIQUES PRÃ‰ALABLES â€” Consommation Ã©lectrique (Tapo P115)
=============================================================================
Objectif : caractÃ©riser rigoureusement les sÃ©ries AVANT toute batterie de
tests statistiques, afin de choisir les tests valides (parametrique vs non
parametrique, iid vs sÃ©rie dÃ©pendante) et de documenter les hypothÃ¨ses.

8 Ã©tapes :
  E1  Chargement + troncature de la phase de mise en route
  E2  RÃ©Ã©chantillonnage sur grille rÃ©guliÃ¨re (gestion du jitter ~5,4 s)
  E3  Statistiques descriptives complÃ¨tes par prise
  E4  Analyse des distributions (histogrammes, normalitÃ©, QQ-plots)
  E5  StationnaritÃ© (ADF + KPSS, lecture croisÃ©e)
  E6  Structure de dÃ©pendance (ACF, PACF, Ljung-Box)
  E7  Comparaisons inter-prises (corrÃ©lations, homogÃ©nÃ©itÃ© des variances)
  E8  SynthÃ¨se : recommandations de tests + exports (JSON, PNG, XLSX)

Sorties (dossier ./analyses_prealables/) :
  - 01_descriptives.xlsx        statistiques par prise et par pas d'agrÃ©gation
  - 02_distributions.png        histogrammes + QQ-plots (3 prises)
  - 03_series_temporelles.png   chronogrammes puissances
  - 04_acf_pacf.png             autocorrÃ©logrammes
  - 05_correlations.png         matrice de corrÃ©lation inter-prises
  - rapport_prealables.json     tous les rÃ©sultats machine-lisibles
  - Console : synthÃ¨se et recommandations pour la suite des tests

DÃ©pendances : pip install pandas scipy statsmodels matplotlib sqlalchemy psycopg2-binary openpyxl
Usage       : python analyses_prealables.py
=============================================================================
"""

import json
import os
import warnings
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from scipy import stats
from sqlalchemy import create_engine
from statsmodels.graphics.tsaplots import plot_acf, plot_pacf
from statsmodels.stats.diagnostic import acorr_ljungbox
from statsmodels.tsa.stattools import adfuller, kpss

warnings.filterwarnings("ignore")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
DB_URL = os.getenv("TAPO_DB_URL",
                   "postgresql://tapo:CHANGEME_VOIR_ENV@localhost:5432/tapo")
DEBUT_SERIE_PROPRE = os.getenv("QC_START", "2026-08-24T14:05:00+00:00")
TZ_LOCALE = "Africa/Douala"
PAS_GRILLE = "10s"          # grille rÃ©guliÃ¨re : absorbe le jitter (pas effectif 5,4 s)
PAS_AGREGATION = "1min"     # second niveau pour stats agrÃ©gÃ©es
ALPHA = 0.05
OUTDIR = "analyses_prealables"

os.makedirs(OUTDIR, exist_ok=True)
plt.rcParams.update({"figure.dpi": 120, "font.size": 9})

rapport = {"genere_le": datetime.now(timezone.utc).isoformat(),
           "parametres": {"debut_serie": DEBUT_SERIE_PROPRE,
                          "pas_grille": PAS_GRILLE, "alpha": ALPHA},
           "etapes": {}}


def titre(txt):
    print("\n" + "=" * 78 + f"\n{txt}\n" + "=" * 78)


# ===========================================================================
# E1 â€” CHARGEMENT + TRONCATURE
# ===========================================================================
titre("E1 â€” Chargement des donnÃ©es")
engine = create_engine(DB_URL)
df = pd.read_sql(
    'SELECT device_name, "timestamp", current_power_mw, today_energy_wh, '
    "month_energy_wh, on_state FROM tapo_readings "
    'WHERE "timestamp" >= %(debut)s ORDER BY "timestamp"',
    engine, params={"debut": DEBUT_SERIE_PROPRE})
df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
df["puissance_w"] = df["current_power_mw"] / 1000.0
prises = sorted(df["device_name"].unique())

print(f"Lignes : {len(df)} | Prises : {prises}")
print(f"FenÃªtre : {df['timestamp'].min()} -> {df['timestamp'].max()} "
      f"({(df['timestamp'].max() - df['timestamp'].min())})")
rapport["etapes"]["E1"] = {"n_lignes": int(len(df)), "prises": prises,
                           "debut": str(df["timestamp"].min()),
                           "fin": str(df["timestamp"].max())}

# ===========================================================================
# E2 â€” RÃ‰Ã‰CHANTILLONNAGE SUR GRILLE RÃ‰GULIÃˆRE
# ===========================================================================
# Justification : le pas effectif est ~5,4 s avec jitter et rares trous de
# 20-45 s. Une grille rÃ©guliÃ¨re Ã  10 s (moyenne des points du bin) rend les
# sÃ©ries comparables entre prises et compatibles avec ACF/tests temporels.
# Les bins vides (trous) restent NaN : ils sont comptÃ©s, PAS interpolÃ©s ici â€”
# l'imputation Ã©ventuelle est une dÃ©cision d'analyse Ã  documenter.
titre(f"E2 â€” RÃ©Ã©chantillonnage sur grille {PAS_GRILLE}")
series = {}
for p in prises:
    s = (df[df["device_name"] == p]
         .set_index("timestamp")["puissance_w"]
         .resample(PAS_GRILLE).mean())
    series[p] = s
    pct_vides = 100 * s.isna().mean()
    print(f"  {p}: {len(s)} bins, {pct_vides:.2f} % vides (trous de collecte)")
    rapport["etapes"].setdefault("E2", {})[p] = {
        "n_bins": int(len(s)), "pct_bins_vides": round(float(pct_vides), 2)}

grille = pd.DataFrame(series)  # colonnes = prises, index = temps rÃ©gulier

# ===========================================================================
# E3 â€” STATISTIQUES DESCRIPTIVES
# ===========================================================================
titre("E3 â€” Statistiques descriptives (puissance, W)")
lignes_desc = []
for p in prises:
    s = grille[p].dropna()
    q = s.quantile([0.01, 0.05, 0.25, 0.5, 0.75, 0.95, 0.99])
    d = {
        "prise": p, "n": int(s.size),
        "moyenne": s.mean(), "ecart_type": s.std(ddof=1),
        "cv_pct": 100 * s.std(ddof=1) / s.mean() if s.mean() else np.nan,
        "min": s.min(), "p01": q[0.01], "p05": q[0.05], "q1": q[0.25],
        "mediane": q[0.5], "q3": q[0.75], "p95": q[0.95], "p99": q[0.99],
        "max": s.max(), "iqr": q[0.75] - q[0.25],
        "asymetrie_skew": stats.skew(s),
        "aplatissement_kurtosis": stats.kurtosis(s),  # excÃ¨s (normale = 0)
    }
    lignes_desc.append(d)
    print(f"  {p}: moy={d['moyenne']:.1f} W  Ïƒ={d['ecart_type']:.1f}  "
          f"CV={d['cv_pct']:.1f} %  med={d['mediane']:.1f}  "
          f"skew={d['asymetrie_skew']:.2f}  kurt={d['aplatissement_kurtosis']:.2f}")
desc = pd.DataFrame(lignes_desc).set_index("prise").round(2)
rapport["etapes"]["E3"] = json.loads(desc.to_json(orient="index"))

# AgrÃ©gation minute (utile pour les tests qui exigent moins de dÃ©pendance)
minute = pd.DataFrame({p: grille[p].resample(PAS_AGREGATION).mean()
                       for p in prises})

with pd.ExcelWriter(f"{OUTDIR}/01_descriptives.xlsx", engine="openpyxl") as xl:
    desc.to_excel(xl, sheet_name=f"Grille {PAS_GRILLE}")
    minute.describe().round(2).T.to_excel(xl, sheet_name=f"AgrÃ©gÃ© {PAS_AGREGATION}")

# ===========================================================================
# E4 â€” DISTRIBUTIONS ET NORMALITÃ‰
# ===========================================================================
# Trois tests complÃ©mentaires ; Ã©chantillonnage Ã  5000 points max pour
# Shapiro (limite de validitÃ© de l'implÃ©mentation).
titre("E4 â€” Distributions et tests de normalitÃ©")
fig, axes = plt.subplots(2, len(prises), figsize=(5 * len(prises), 7))
norm_res = {}
for i, p in enumerate(prises):
    s = grille[p].dropna()
    ech = s.sample(min(len(s), 5000), random_state=42)
    sh_stat, sh_p = stats.shapiro(ech)
    da_stat, da_p = stats.normaltest(s)                      # D'Agostino-Pearson
    ks_stat, ks_p = stats.kstest((s - s.mean()) / s.std(ddof=1), "norm")
    normal = all(pv > ALPHA for pv in (sh_p, da_p, ks_p))
    norm_res[p] = {"shapiro_p": float(sh_p), "dagostino_p": float(da_p),
                   "ks_p": float(ks_p), "normalite_retenue": bool(normal)}
    print(f"  {p}: Shapiro p={sh_p:.2e} | D'Agostino p={da_p:.2e} | "
          f"KS p={ks_p:.2e} -> {'normale' if normal else 'NON normale'}")

    axes[0, i].hist(s, bins=60, color="#4472c4", edgecolor="white")
    axes[0, i].set_title(f"{p} â€” histogramme")
    axes[0, i].set_xlabel("Puissance (W)")
    stats.probplot(s, dist="norm", plot=axes[1, i])
    axes[1, i].set_title(f"{p} â€” QQ-plot")
fig.tight_layout()
fig.savefig(f"{OUTDIR}/02_distributions.png")
plt.close(fig)
rapport["etapes"]["E4"] = norm_res

# ===========================================================================
# E5 â€” STATIONNARITÃ‰ (ADF + KPSS, lecture croisÃ©e)
# ===========================================================================
# ADF : H0 = racine unitaire (non stationnaire) -> p < Î± = stationnaire
# KPSS: H0 = stationnaire                      -> p < Î± = NON stationnaire
# La conclusion n'est solide que si les deux tests concordent.
titre("E5 â€” StationnaritÃ© (ADF + KPSS)")
stat_res = {}
for p in prises:
    s = grille[p].dropna()
    adf_stat, adf_p, *_ = adfuller(s, autolag="AIC")
    kpss_stat, kpss_p, *_ = kpss(s, regression="c", nlags="auto")
    if adf_p < ALPHA and kpss_p > ALPHA:
        concl = "stationnaire"
    elif adf_p >= ALPHA and kpss_p <= ALPHA:
        concl = "NON stationnaire"
    else:
        concl = "indÃ©terminÃ© (tests discordants)"
    stat_res[p] = {"adf_p": float(adf_p), "kpss_p": float(kpss_p),
                   "conclusion": concl}
    print(f"  {p}: ADF p={adf_p:.3g} | KPSS p={kpss_p:.3g} -> {concl}")
rapport["etapes"]["E5"] = stat_res

# Chronogrammes (support visuel de la stationnaritÃ©)
fig, axes = plt.subplots(len(prises), 1, figsize=(12, 2.6 * len(prises)),
                         sharex=True)
for ax, p in zip(np.atleast_1d(axes), prises):
    idx_local = grille.index.tz_convert(TZ_LOCALE)
    ax.plot(idx_local, grille[p], lw=0.6, color="#4472c4")
    ax.set_ylabel(f"{p}\n(W)")
axes[-1].set_xlabel(f"Heure locale ({TZ_LOCALE})")
fig.suptitle("SÃ©ries de puissance sur grille rÃ©guliÃ¨re")
fig.tight_layout()
fig.savefig(f"{OUTDIR}/03_series_temporelles.png")
plt.close(fig)

# ===========================================================================
# E6 â€” STRUCTURE DE DÃ‰PENDANCE (ACF / PACF / Ljung-Box)
# ===========================================================================
# Une autocorrÃ©lation forte invalide l'hypothÃ¨se iid de nombreux tests :
# elle impose d'agrÃ©ger (minute+) ou d'utiliser des tests robustes.
titre("E6 â€” AutocorrÃ©lation (Ljung-Box, lag 20)")
fig, axes = plt.subplots(len(prises), 2, figsize=(11, 2.8 * len(prises)))
dep_res = {}
for i, p in enumerate(prises):
    s = grille[p].dropna()
    lb = acorr_ljungbox(s, lags=[20], return_df=True)
    lb_p = float(lb["lb_pvalue"].iloc[0])
    dep_res[p] = {"ljungbox_lag20_p": lb_p,
                  "dependance_serielle": bool(lb_p < ALPHA)}
    print(f"  {p}: Ljung-Box(20) p={lb_p:.2e} -> "
          f"{'dÃ©pendance sÃ©rielle marquÃ©e' if lb_p < ALPHA else 'compatible iid'}")
    plot_acf(s, ax=axes[i, 0], lags=60, title=f"{p} â€” ACF")
    plot_pacf(s, ax=axes[i, 1], lags=60, method="ywm", title=f"{p} â€” PACF")
fig.tight_layout()
fig.savefig(f"{OUTDIR}/04_acf_pacf.png")
plt.close(fig)
rapport["etapes"]["E6"] = dep_res

# ===========================================================================
# E7 â€” COMPARAISONS INTER-PRISES
# ===========================================================================
titre("E7 â€” Comparaisons inter-prises")
# CorrÃ©lations (Pearson + Spearman) sur bins simultanÃ©s complets
complet = grille.dropna()
corr_p = complet.corr(method="pearson").round(3)
corr_s = complet.corr(method="spearman").round(3)
print("CorrÃ©lation de Spearman (robuste) :\n", corr_s.to_string())

# HomogÃ©nÃ©itÃ© des variances (Levene, robuste Ã  la non-normalitÃ©)
lev_stat, lev_p = stats.levene(*[grille[p].dropna() for p in prises],
                               center="median")
# Comparaison globale des niveaux (Kruskal-Wallis, non paramÃ©trique)
kw_stat, kw_p = stats.kruskal(*[grille[p].dropna() for p in prises])
print(f"Levene (variances)      : p={lev_p:.3g} -> "
      f"{'hÃ©tÃ©rogÃ¨nes' if lev_p < ALPHA else 'homogÃ¨nes'}")
print(f"Kruskal-Wallis (niveaux): p={kw_p:.3g} -> "
      f"{'au moins une prise diffÃ¨re' if kw_p < ALPHA else 'pas de diffÃ©rence dÃ©tectÃ©e'}")
rapport["etapes"]["E7"] = {
    "spearman": json.loads(corr_s.to_json()),
    "levene_p": float(lev_p), "kruskal_p": float(kw_p)}

fig, ax = plt.subplots(figsize=(5, 4))
im = ax.imshow(corr_s, vmin=-1, vmax=1, cmap="RdBu_r")
ax.set_xticks(range(len(prises)), prises, rotation=45)
ax.set_yticks(range(len(prises)), prises)
for a in range(len(prises)):
    for b in range(len(prises)):
        ax.text(b, a, corr_s.iloc[a, b], ha="center", va="center")
fig.colorbar(im, label="Ï de Spearman")
ax.set_title("CorrÃ©lations inter-prises (Spearman)")
fig.tight_layout()
fig.savefig(f"{OUTDIR}/05_correlations.png")
plt.close(fig)

# ===========================================================================
# E8 â€” SYNTHÃˆSE ET RECOMMANDATIONS
# ===========================================================================
titre("E8 â€” SynthÃ¨se : implications pour les tests Ã  venir")
recos = []
if not all(r["normalite_retenue"] for r in norm_res.values()):
    recos.append("NormalitÃ© rejetÃ©e sur au moins une prise -> privilÃ©gier les "
                 "tests NON paramÃ©triques (Mann-Whitney, Kruskal-Wallis, "
                 "Spearman) ou travailler sur agrÃ©gats/transformations.")
if any(r["dependance_serielle"] for r in dep_res.values()):
    recos.append("DÃ©pendance sÃ©rielle marquÃ©e -> les tests supposant l'iid "
                 f"doivent s'appliquer sur donnÃ©es agrÃ©gÃ©es ({PAS_AGREGATION} "
                 "ou plus), ou par blocs espacÃ©s ; sinon p-values invalides.")
if any("NON" in r["conclusion"] for r in stat_res.values()):
    recos.append("Non-stationnaritÃ© dÃ©tectÃ©e -> diffÃ©rencier ou segmenter par "
                 "rÃ©gime avant tests de moyenne/variance sur la sÃ©rie fine.")
if lev_p < ALPHA:
    recos.append("Variances hÃ©tÃ©rogÃ¨nes entre prises -> proscrire l'ANOVA "
                 "classique ; utiliser Welch ou non paramÃ©trique.")
if not recos:
    recos.append("Aucun obstacle majeur dÃ©tectÃ© : les tests paramÃ©triques "
                 "standards sont envisageables sur ces sÃ©ries.")
for r in recos:
    print("  â€¢ " + r)
rapport["etapes"]["E8_recommandations"] = recos

with open(f"{OUTDIR}/rapport_prealables.json", "w", encoding="utf-8") as f:
    json.dump(rapport, f, ensure_ascii=False, indent=2, default=str)

print(f"\nExports Ã©crits dans ./{OUTDIR}/ "
      "(XLSX, 4 PNG, rapport_prealables.json)")