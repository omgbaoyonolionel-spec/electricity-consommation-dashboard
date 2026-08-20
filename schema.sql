CREATE TABLE IF NOT EXISTS tapo_readings (
    id               BIGSERIAL PRIMARY KEY,
    device_name      TEXT NOT NULL,
    ip               TEXT NOT NULL,
    "timestamp"      TIMESTAMPTZ NOT NULL,
    current_power_mw INTEGER NOT NULL CHECK (current_power_mw >= 0),
    today_energy_wh  INTEGER NOT NULL CHECK (today_energy_wh >= 0),
    month_energy_wh  INTEGER NOT NULL CHECK (month_energy_wh >= 0),
    on_state         BOOLEAN NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_tapo_readings_device_timestamp
    ON tapo_readings (device_name, "timestamp" DESC);
