# %% [markdown]
# # PlantIQ MVP: Task S1-AI-02 — EDA & Demo-Plant Selection
# ## Empirical Profiling of Kaggle Solar Datasets using Polars & DuckDB
#
# This script/notebook executes an end-to-end, reproducible empirical profile of the two solar PV plants in the Kaggle dataset:
# - **Plant 1:** `Plant_1_Generation_Data.csv` & `Plant_1_Weather_Sensor_Data.csv`
# - **Plant 2:** `Plant_2_Generation_Data.csv` & `Plant_2_Weather_Sensor_Data.csv`
#
# Constraints: Exclusively uses **Polars** and **DuckDB** (zero Pandas dependency).

# %%
import os
from pathlib import Path
import duckdb
import polars as pl

# Configure Polars display options
pl.Config.set_tbl_rows(25)
pl.Config.set_tbl_cols(12)
pl.Config.set_tbl_width_chars(120)

# Resolve repository root and dataset directory
CWD = Path.cwd()
DATA_DIR = Path("datasets") if Path("datasets").exists() else Path("../datasets")
if not (DATA_DIR / "Plant_1_Generation_Data.csv").exists():
    DATA_DIR = Path("Datasets") if Path("Datasets").exists() else Path("../Datasets")
if not (DATA_DIR / "Plant_1_Generation_Data.csv").exists():
    DATA_DIR = Path("/home/stpl/Desktop/plantiq/datasets")

print(f"Working Directory: {CWD}")
print(f"Data Directory:    {DATA_DIR.resolve()}")

# Define file paths
P1_GEN_PATH = str((DATA_DIR / "Plant_1_Generation_Data.csv").resolve())
P1_WTR_PATH = str((DATA_DIR / "Plant_1_Weather_Sensor_Data.csv").resolve())
P2_GEN_PATH = str((DATA_DIR / "Plant_2_Generation_Data.csv").resolve())
P2_WTR_PATH = str((DATA_DIR / "Plant_2_Weather_Sensor_Data.csv").resolve())

con = duckdb.connect(database=":memory:")
print(f"DuckDB Version: {duckdb.__version__}")
print(f"Polars Version: {pl.__version__}")

# %% [markdown]
# ---
# ## 1. Scope & Record Counts
# Exact row counts, distinct `SOURCE_KEY` counts, and date ranges across all 4 files.

# %%
scope_query = f'''
SELECT 
    'Plant 1 Generation' AS dataset_file,
    count(*) AS row_count,
    count(DISTINCT SOURCE_KEY) AS distinct_source_keys,
    min(strptime(DATE_TIME, '%d-%m-%Y %H:%M')) AS min_timestamp,
    max(strptime(DATE_TIME, '%d-%m-%Y %H:%M')) AS max_timestamp,
    date_diff('day', min(strptime(DATE_TIME, '%d-%m-%Y %H:%M')), max(strptime(DATE_TIME, '%d-%m-%Y %H:%M'))) + 1 AS calendar_days
FROM read_csv('{P1_GEN_PATH}', all_varchar=true)

UNION ALL

SELECT 
    'Plant 1 Weather',
    count(*),
    count(DISTINCT SOURCE_KEY),
    min(strptime(DATE_TIME, '%Y-%m-%d %H:%M:%S')),
    max(strptime(DATE_TIME, '%Y-%m-%d %H:%M:%S')),
    date_diff('day', min(strptime(DATE_TIME, '%Y-%m-%d %H:%M:%S')), max(strptime(DATE_TIME, '%Y-%m-%d %H:%M:%S'))) + 1
FROM read_csv('{P1_WTR_PATH}', all_varchar=true)

UNION ALL

SELECT 
    'Plant 2 Generation',
    count(*),
    count(DISTINCT SOURCE_KEY),
    min(strptime(DATE_TIME, '%Y-%m-%d %H:%M:%S')),
    max(strptime(DATE_TIME, '%Y-%m-%d %H:%M:%S')),
    date_diff('day', min(strptime(DATE_TIME, '%Y-%m-%d %H:%M:%S')), max(strptime(DATE_TIME, '%Y-%m-%d %H:%M:%S'))) + 1
FROM read_csv('{P2_GEN_PATH}', all_varchar=true)

UNION ALL

SELECT 
    'Plant 2 Weather',
    count(*),
    count(DISTINCT SOURCE_KEY),
    min(strptime(DATE_TIME, '%Y-%m-%d %H:%M:%S')),
    max(strptime(DATE_TIME, '%Y-%m-%d %H:%M:%S')),
    date_diff('day', min(strptime(DATE_TIME, '%Y-%m-%d %H:%M:%S')), max(strptime(DATE_TIME, '%Y-%m-%d %H:%M:%S'))) + 1
FROM read_csv('{P2_WTR_PATH}', all_varchar=true);
'''

scope_df = con.execute(scope_query).pl()
print(scope_df)

# %% [markdown]
# ---
# ## 2. Timestamp Formats & Empirical strptime Verification
# Verifying day-first vs ISO formats across all files.

# %%
raw_samples_query = f'''
(SELECT 'Plant 1 Gen' AS file, DATE_TIME AS raw_sample FROM read_csv('{P1_GEN_PATH}', all_varchar=true) LIMIT 3)
UNION ALL
(SELECT 'Plant 1 Weather', DATE_TIME FROM read_csv('{P1_WTR_PATH}', all_varchar=true) LIMIT 3)
UNION ALL
(SELECT 'Plant 2 Gen', DATE_TIME FROM read_csv('{P2_GEN_PATH}', all_varchar=true) LIMIT 3)
UNION ALL
(SELECT 'Plant 2 Weather', DATE_TIME FROM read_csv('{P2_WTR_PATH}', all_varchar=true) LIMIT 3);
'''
raw_samples = con.execute(raw_samples_query).pl()
print("Raw Timestamp String Samples:")
print(raw_samples)

FORMAT_SPECS = {
    "Plant 1 Generation": {"path": P1_GEN_PATH, "format": "%d-%m-%Y %H:%M", "style": "Day-First (DD-MM-YYYY HH:MM)"},
    "Plant 1 Weather":    {"path": P1_WTR_PATH, "format": "%Y-%m-%d %H:%M:%S", "style": "ISO 8601 (YYYY-MM-DD HH:MM:SS)"},
    "Plant 2 Generation": {"path": P2_GEN_PATH, "format": "%Y-%m-%d %H:%M:%S", "style": "ISO 8601 (YYYY-MM-DD HH:MM:SS)"},
    "Plant 2 Weather":    {"path": P2_WTR_PATH, "format": "%Y-%m-%d %H:%M:%S", "style": "ISO 8601 (YYYY-MM-DD HH:MM:SS)"},
}

verification_rows = []
for name, spec in FORMAT_SPECS.items():
    df_raw = pl.read_csv(spec["path"], columns=["DATE_TIME"])
    parsed = df_raw["DATE_TIME"].str.strptime(pl.Datetime, format=spec["format"], strict=False)
    null_count = parsed.is_null().sum()
    verification_rows.append({
        "File": name,
        "Format String": spec["format"],
        "Format Style": spec["style"],
        "Total Rows": len(df_raw),
        "Parsed Successfully": len(df_raw) - null_count,
        "Failed / Nulls": null_count,
        "Earliest": str(parsed.min()),
        "Latest": str(parsed.max())
    })

verify_df = pl.DataFrame(verification_rows)
print("\nTimestamp Verification Results:")
print(verify_df)

# %% [markdown]
# ---
# ## 3. Sampling Intervals & Telemetry Gaps
# Quantifying 15-minute expected intervals (96/day, 3,264 per device over 34 days).

# %%
EXPECTED_INTERVALS = 34 * 96  # 3264 intervals

gen_schema = {
    'DC_POWER': pl.Float64,
    'AC_POWER': pl.Float64,
    'DAILY_YIELD': pl.Float64,
    'TOTAL_YIELD': pl.Float64
}

df1_gen = pl.read_csv(P1_GEN_PATH, schema_overrides=gen_schema).with_columns(
    pl.col("DATE_TIME").str.strptime(pl.Datetime, format="%d-%m-%Y %H:%M").alias("timestamp")
)

df2_gen = pl.read_csv(P2_GEN_PATH, schema_overrides=gen_schema).with_columns(
    pl.col("DATE_TIME").str.strptime(pl.Datetime, format="%Y-%m-%d %H:%M:%S").alias("timestamp")
)

cov1 = df1_gen.group_by("SOURCE_KEY").agg(
    pl.len().alias("recorded_intervals"),
    (EXPECTED_INTERVALS - pl.len()).alias("missing_intervals"),
    (pl.len() / EXPECTED_INTERVALS * 100).round(2).alias("coverage_pct")
).sort("recorded_intervals")

print("Plant 1: Lowest 5 Coverage Inverters:")
print(cov1.head(5))

cov2 = df2_gen.group_by("SOURCE_KEY").agg(
    pl.len().alias("recorded_intervals"),
    (EXPECTED_INTERVALS - pl.len()).alias("missing_intervals"),
    (pl.len() / EXPECTED_INTERVALS * 100).round(2).alias("coverage_pct")
).sort("recorded_intervals")

print("\nPlant 2: Lowest 5 Coverage Inverters:")
print(cov2.head(5))

# Daily interval counts and missing full-day analysis
daily_gaps_sql = f'''
WITH p1_daily AS (
    SELECT 
        'Plant 1' AS plant,
        SOURCE_KEY,
        CAST(strptime(DATE_TIME, '%d-%m-%Y %H:%M') AS DATE) AS log_date,
        count(*) AS cnt
    FROM read_csv('{P1_GEN_PATH}', all_varchar=true)
    GROUP BY SOURCE_KEY, log_date
),
p2_daily AS (
    SELECT 
        'Plant 2' AS plant,
        SOURCE_KEY,
        CAST(DATE_TIME::TIMESTAMP AS DATE) AS log_date,
        count(*) AS cnt
    FROM read_csv('{P2_GEN_PATH}', all_varchar=true)
    GROUP BY SOURCE_KEY, log_date
),
combined AS (
    SELECT * FROM p1_daily UNION ALL SELECT * FROM p2_daily
)
SELECT 
    plant,
    count(*) AS total_inverter_days,
    min(cnt) AS min_intervals_day,
    round(avg(cnt), 2) AS avg_intervals_day,
    max(cnt) AS max_intervals_day,
    count(CASE WHEN cnt = 96 THEN 1 END) AS full_96_days,
    count(CASE WHEN cnt < 96 THEN 1 END) AS partial_days,
    (22 * 34) - count(*) AS completely_missing_inverter_days
FROM combined
GROUP BY plant;
'''

print("\nDaily Inverter Interval Distribution:")
print(con.execute(daily_gaps_sql).pl())

# Defective inverters in Plant 2
p2_outage_sql = f'''
WITH all_dates AS (
    SELECT DISTINCT CAST(DATE_TIME::TIMESTAMP AS DATE) AS dt
    FROM read_csv('{P2_GEN_PATH}', all_varchar=true)
),
all_inverters AS (
    SELECT DISTINCT SOURCE_KEY
    FROM read_csv('{P2_GEN_PATH}', all_varchar=true)
),
grid AS (
    SELECT i.SOURCE_KEY, d.dt FROM all_inverters i CROSS JOIN all_dates d
),
actual AS (
    SELECT SOURCE_KEY, CAST(DATE_TIME::TIMESTAMP AS DATE) AS dt, count(*) AS cnt
    FROM read_csv('{P2_GEN_PATH}', all_varchar=true)
    GROUP BY SOURCE_KEY, dt
)
SELECT 
    g.SOURCE_KEY,
    count(CASE WHEN a.cnt IS NULL THEN 1 END) AS completely_missing_days,
    string_agg(CASE WHEN a.cnt IS NULL THEN strftime(g.dt, '%Y-%m-%d') END, ', ') AS missing_date_list
FROM grid g
LEFT JOIN actual a ON g.SOURCE_KEY = a.SOURCE_KEY AND g.dt = a.dt
GROUP BY g.SOURCE_KEY
HAVING completely_missing_days > 0
ORDER BY completely_missing_days DESC;
'''

print("\nPlant 2 Outage Cluster (8 full consecutive missing days):")
print(con.execute(p2_outage_sql).pl())

# %% [markdown]
# ---
# ## 4. Unit Sanity Check: Power Scaling Artifacts & Irradiance Physical Range
# Identifying the 10x DC scaling artifact and confirming irradiance units.

# %%
eff_check_sql = f'''
WITH p1_eff AS (
    SELECT 
        'Plant 1 (Raw)' AS label,
        AC_POWER / DC_POWER AS eff
    FROM read_csv('{P1_GEN_PATH}')
    WHERE DC_POWER > 100 AND AC_POWER > 10
),
p1_scaled AS (
    SELECT 
        'Plant 1 (DC * 0.1 Corrected)' AS label,
        AC_POWER / (DC_POWER * 0.1) AS eff
    FROM read_csv('{P1_GEN_PATH}')
    WHERE DC_POWER > 100 AND AC_POWER > 10
),
p2_eff AS (
    SELECT 
        'Plant 2 (Raw / Unscaled)' AS label,
        AC_POWER / DC_POWER AS eff
    FROM read_csv('{P2_GEN_PATH}')
    WHERE DC_POWER > 10 AND AC_POWER > 1
),
combined_eff AS (
    SELECT * FROM p1_eff UNION ALL SELECT * FROM p1_scaled UNION ALL SELECT * FROM p2_eff
)
SELECT 
    label,
    round(min(eff), 4) AS min_eff,
    round(quantile_cont(eff, 0.05), 4) AS p05_eff,
    round(quantile_cont(eff, 0.25), 4) AS p25_eff,
    round(quantile_cont(eff, 0.50), 4) AS median_eff,
    round(quantile_cont(eff, 0.75), 4) AS p75_eff,
    round(quantile_cont(eff, 0.95), 4) AS p95_eff,
    round(max(eff), 4) AS max_eff
FROM combined_eff
GROUP BY label;
'''

print(con.execute(eff_check_sql).pl())

irr_check_sql = f'''
SELECT 
    'Plant 1 Weather' AS station,
    round(min(IRRADIATION), 4) AS min_val,
    round(quantile_cont(IRRADIATION, 0.50), 4) AS median_all,
    round(quantile_cont(CASE WHEN IRRADIATION > 0 THEN IRRADIATION END, 0.50), 4) AS median_daylight,
    round(quantile_cont(IRRADIATION, 0.99), 4) AS p99_val,
    round(max(IRRADIATION), 4) AS max_val
FROM read_csv('{P1_WTR_PATH}')

UNION ALL

SELECT 
    'Plant 2 Weather',
    round(min(IRRADIATION), 4),
    round(quantile_cont(IRRADIATION, 0.50), 4),
    round(quantile_cont(CASE WHEN IRRADIATION > 0 THEN IRRADIATION END, 0.50), 4),
    round(quantile_cont(IRRADIATION, 0.99), 4),
    round(max(IRRADIATION), 4)
FROM read_csv('{P2_WTR_PATH}');
'''

print("\nIrradiation Statistics (kW/m²):")
print(con.execute(irr_check_sql).pl())

# %% [markdown]
# ---
# ## 5. Rated Capacity & Specific Yield Arithmetic
# Estimating per-inverter rated DC capacity from p99 DC power, deriving total plant capacity, and calculating specific yield.

# %%
inv_capacity_sql = f'''
WITH p1_inv AS (
    SELECT 
        SOURCE_KEY,
        quantile_cont(DC_POWER * 0.1, 0.99) AS p99_dc,
        max(DC_POWER * 0.1) AS max_dc,
        quantile_cont(AC_POWER, 0.99) AS p99_ac,
        max(AC_POWER) AS max_ac
    FROM read_csv('{P1_GEN_PATH}')
    GROUP BY SOURCE_KEY
),
p2_inv AS (
    SELECT 
        SOURCE_KEY,
        quantile_cont(DC_POWER, 0.99) AS p99_dc,
        max(DC_POWER) AS max_dc,
        quantile_cont(AC_POWER, 0.99) AS p99_ac,
        max(AC_POWER) AS max_ac
    FROM read_csv('{P2_GEN_PATH}')
    GROUP BY SOURCE_KEY
)
SELECT 
    'Plant 1' AS plant,
    count(*) AS num_inverters,
    round(min(p99_dc), 2) AS min_inv_p99_dc_kwp,
    round(avg(p99_dc), 2) AS avg_inv_p99_dc_kwp,
    round(max(p99_dc), 2) AS max_inv_p99_dc_kwp,
    round(sum(p99_dc), 2) AS total_plant_capacity_kwp,
    round(sum(p99_dc) / 1000, 3) AS total_plant_capacity_mwp
FROM p1_inv

UNION ALL

SELECT 
    'Plant 2',
    count(*),
    round(min(p99_dc), 2),
    round(avg(p99_dc), 2),
    round(max(p99_dc), 2),
    round(sum(p99_dc), 2),
    round(sum(p99_dc) / 1000, 3)
FROM p2_inv;
'''

capacity_summary = con.execute(inv_capacity_sql).pl()
print(capacity_summary)

specific_yield_sql = f'''
WITH p1_daily AS (
    SELECT 
        CAST(strptime(DATE_TIME, '%d-%m-%Y %H:%M') AS DATE) AS log_date,
        sum(AC_POWER * 0.25) AS daily_ac_kwh
    FROM read_csv('{P1_GEN_PATH}')
    GROUP BY log_date
),
p2_daily AS (
    SELECT 
        CAST(DATE_TIME::TIMESTAMP AS DATE) AS log_date,
        sum(AC_POWER * 0.25) AS daily_ac_kwh
    FROM read_csv('{P2_GEN_PATH}')
    GROUP BY log_date
)
SELECT 
    'Plant 1 (Corrected DC = 28.29 MWp)' AS scenario,
    round(min(daily_ac_kwh), 0) AS min_daily_kwh,
    round(avg(daily_ac_kwh), 0) AS avg_daily_kwh,
    round(max(daily_ac_kwh), 0) AS max_daily_kwh,
    round(min(daily_ac_kwh) / 28286.79, 2) AS min_specific_yield_kwh_per_kwp,
    round(avg(daily_ac_kwh) / 28286.79, 2) AS avg_specific_yield_kwh_per_kwp,
    round(max(daily_ac_kwh) / 28286.79, 2) AS max_specific_yield_kwh_per_kwp
FROM p1_daily

UNION ALL

SELECT 
    'Plant 1 (Uncorrected DC = 282.87 MWp)',
    round(min(daily_ac_kwh), 0),
    round(avg(daily_ac_kwh), 0),
    round(max(daily_ac_kwh), 0),
    round(min(daily_ac_kwh) / 282867.9, 3),
    round(avg(daily_ac_kwh) / 282867.9, 3),
    round(max(daily_ac_kwh) / 282867.9, 3)
FROM p1_daily

UNION ALL

SELECT 
    'Plant 2 (Corrected DC = 27.48 MWp)',
    round(min(daily_ac_kwh), 0),
    round(avg(daily_ac_kwh), 0),
    round(max(daily_ac_kwh), 0),
    round(min(daily_ac_kwh) / 27479.68, 2),
    round(avg(daily_ac_kwh) / 27479.68, 2),
    round(max(daily_ac_kwh) / 27479.68, 2)
FROM p2_daily;
'''

print("\nSpecific Yield Comparison (kWh/kWp/day):")
print(con.execute(specific_yield_sql).pl())

# %% [markdown]
# ---
# ## 6. Yield Counters: Monotonicity, Resets, and Integrity
# Checking cumulative total yield counter integrity vs integrated energy.

# %%
w1 = df1_gen.sort(["SOURCE_KEY", "timestamp"]).with_columns(
    pl.col("TOTAL_YIELD").diff().over("SOURCE_KEY").alias("yield_step")
)

w2 = df2_gen.sort(["SOURCE_KEY", "timestamp"]).with_columns(
    pl.col("TOTAL_YIELD").diff().over("SOURCE_KEY").alias("yield_step")
)

neg1 = w1.filter(pl.col("yield_step") < 0)
neg2 = w2.filter(pl.col("yield_step") < 0)

print(f"Plant 1: Negative Yield Steps: {len(neg1)} (Strictly Monotonic: {len(neg1) == 0})")
print(f"Plant 2: Negative Yield Steps: {len(neg2)} (Strictly Monotonic: {len(neg2) == 0})")

print("\nPlant 1 TOTAL_YIELD Range:", df1_gen['TOTAL_YIELD'].min(), "to", df1_gen['TOTAL_YIELD'].max())
print("Plant 2 TOTAL_YIELD Range:", df2_gen['TOTAL_YIELD'].min(), "to", df2_gen['TOTAL_YIELD'].max())

print("\nSample Plant 2 TOTAL_YIELD Negative Drops / Resets:")
print(neg2.select(["SOURCE_KEY", "timestamp", "TOTAL_YIELD", "yield_step"]).head(8))

comp1 = df1_gen.group_by(["SOURCE_KEY", pl.col("timestamp").dt.date().alias("date")]).agg(
    (pl.col("AC_POWER") * 0.25).sum().alias("integrated_kwh"),
    pl.col("DAILY_YIELD").max().alias("max_daily_yield"),
    (pl.col("TOTAL_YIELD").max() - pl.col("TOTAL_YIELD").min()).alias("delta_total_yield")
).filter(pl.col("max_daily_yield") > 0).with_columns(
    (pl.col("max_daily_yield") / pl.col("integrated_kwh")).alias("ratio_daily_to_integrated"),
    (pl.col("delta_total_yield") - pl.col("max_daily_yield")).abs().alias("total_vs_daily_diff")
)

print("\nPlant 1: DAILY_YIELD vs Integrated Energy Consistency:")
print(f"  Mean Ratio:       {comp1['ratio_daily_to_integrated'].mean():.4f}")
print(f"  Median Ratio:     {comp1['ratio_daily_to_integrated'].median():.4f}")
print(f"  Mean |ΔTY - DY|:  {comp1['total_vs_daily_diff'].mean():.2f} kWh")

comp2 = df2_gen.group_by(["SOURCE_KEY", pl.col("timestamp").dt.date().alias("date")]).agg(
    (pl.col("AC_POWER") * 0.25).sum().alias("integrated_kwh"),
    pl.col("DAILY_YIELD").max().alias("max_daily_yield")
).filter(pl.col("max_daily_yield") > 0).with_columns(
    (pl.col("max_daily_yield") / pl.col("integrated_kwh")).alias("ratio_daily_to_integrated")
)

print("\nPlant 2: DAILY_YIELD vs Integrated Energy Consistency:")
print(f"  Mean Ratio:       {comp2['ratio_daily_to_integrated'].mean():.4f}")
print(f"  Median Ratio:     {comp2['ratio_daily_to_integrated'].median():.4f}")
print(f"  Max Ratio:        {comp2['ratio_daily_to_integrated'].max():.4f}")

# %% [markdown]
# ---
# ## 7. Missing Infrastructure Signals & Downstream Analytics Impact
#
# Assessment of telemetry gaps against IEC 61724-1 standards:
# - **Plant Substation Revenue Meter:** Missing. Plant AC generation must be estimated by aggregating all 22 inverters: $P_{\text{plant}} = \sum_{i=1}^{22} P_{ac, i}$. Cannot quantify MV line/transformer losses.
# - **String-Level Combiner Monitoring:** Missing. Blown string fuses or partial string shading only manifest as small deratings at the aggregated inverter DC level.
# - **Inverter Operating Status Codes / Alarms:** Missing. IEC 61724-1 availability requires equipment state tracking. Heuristic workaround: inverter is deemed down if solar irradiance $G > 50 \text{ W/m}^2$ and $P_{ac} < 0.01 \times P_{\text{rated}}$.
# - **Wind Speed & Wind Direction:** Missing. Faiman/King thermal models require wind speed. Pipeline must directly rely on measured `MODULE_TEMPERATURE` for temperature correction.
# - **DC & AC Operating Voltages / Currents:** Missing. Cannot detect MPPT voltage clipping, string undervoltage, or grid power factor trips.
# - **Block-Level Pyranometers:** Missing. Only 1 central sensor per 28 MW plant. Localized cloud passage causes false underperformance alarms unless filtered by cloud volatility detectors.

# %% [markdown]
# ---
# ## 8. Weather Sensor Granularity & Spatial Resolution

# %%
wtr_granularity_sql = f'''
SELECT 
    'Plant 1' AS plant,
    SOURCE_KEY AS weather_source_key,
    count(*) AS total_readings,
    min(DATE_TIME) AS start_time,
    max(DATE_TIME) AS end_time
FROM read_csv('{P1_WTR_PATH}', all_varchar=true)
GROUP BY SOURCE_KEY

UNION ALL

SELECT 
    'Plant 2',
    SOURCE_KEY,
    count(*),
    min(DATE_TIME),
    max(DATE_TIME)
FROM read_csv('{P2_WTR_PATH}', all_varchar=true)
GROUP BY SOURCE_KEY;
'''

print(con.execute(wtr_granularity_sql).pl())

# %% [markdown]
# ---
# ## 9. Demo-Plant Designation & Comprehensive Analytical Summary
#
# ### 9.1 Plant Designation Recommendation
# - **Surya-A (Primary MVP Demo Plant): Plant 1**
# - **Surya-B (Secondary Stress-Testing Plant): Plant 2**
#
# ### 9.2 One-Paragraph Data-Quality Justification
# **Plant 1 is emphatically designated as Surya-A (Primary Demo Plant)** because its telemetry exhibits exemplary foundational integrity: its cumulative energy counters (`TOTAL_YIELD`) are 100% strictly monotonic (0 negative steps across all 22 inverters over 34 days), its `DAILY_YIELD` tracks integrated AC power with a tight 1.0003 median ratio and an average discrepancy of under 10 kWh, and inverter data coverage is uniformly high (95.1%–96.8%) across the entire fleet without a single full-day inverter dropout. Its single known anomaly—a deterministic 10x multiplier on `DC_POWER`—is an easily calibrated linear scaling artifact that, once corrected ($P_{dc} \times 0.1$), produces an authentic commercial central inverter efficiency of 97.85% and a textbook Indian summer specific yield of 5.50 kWh/kWp/day. Conversely, **Plant 2 is designated as Surya-B (Secondary Plant)** due to severe data degradation: 1,162 negative resets in `TOTAL_YIELD` with values erratically spiking to 2.24 billion, and four inverters (`IQ2d7wF4YD8zU1Q`, `mqwcsP2rE7J0TFp`, `NgDl19wMapZy17u`, `xMbIugepa2P7lBB`) simultaneously suffering 909 missing intervals (~28% telemetry loss) including 8 consecutive missing days (May 21–28, 2020), making Plant 2 an ideal stress-test asset for gap imputation and anomaly detector validation rather than primary MVP benchmarking.
