import pandas as pd
from sqlalchemy import create_engine

engine = create_engine("postgresql://tapo:CHANGEME_VOIR_ENV@localhost:5432/tapo")
df = pd.read_sql("""
    SELECT id, device_name, ip,
           "timestamp" AT TIME ZONE 'Africa/Douala' AS heure_locale,
           ROUND(current_power_mw / 1000.0, 2)      AS puissance_w,
           today_energy_wh, month_energy_wh, on_state
    FROM tapo_readings ORDER BY "timestamp", device_name
""", engine)

with pd.ExcelWriter("historique_tapo.xlsx", engine="openpyxl") as xl:
    df.to_excel(xl, sheet_name="Historique complet", index=False)
    for prise, g in df.groupby("device_name"):
        g.to_excel(xl, sheet_name=prise, index=False)

print(f"{len(df)} lignes exportÃ©es vers historique_tapo.xlsx")