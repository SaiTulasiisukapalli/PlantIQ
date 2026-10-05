# Canonical Dictionary Review & Field Mapping Specification
**Task ID:** S1-AI-03  
**Module:** Ingestion & Schema Standardization  
**Target File:** `/docs/canonical-dictionary-review.md`  
**Reference Specification:** PlantIQ Architecture Spec §12.3 (Telemetry Data Model & Dictionaries)

---

## 1. Executive Summary & Objective

This review reconciles the seeded PlantIQ canonical telemetry dictionary (Spec §12.3) against empirical findings from the Kaggle Solar PV datasets ([Task S1-AI-02](file:///home/stpl/Desktop/plantiq/Datasets/notebooks/01_kaggle_eda.ipynb)).

The canonical dictionary serves as the authoritative, typed contract for all incoming time-series telemetry in the PlantIQ data plane. Every raw sensor signal must either:
1. Map cleanly to a standardized canonical key, data type, and base engineering unit (with conversion applied during ingestion).
2. Map to asset metadata or relational dimension fields (e.g., `plant_id`, `device_id`, `timestamp`).
3. Be explicitly classified as non-canonical or unmapped.

This document establishes the official Kaggle-to-canonical mapping, evaluates adjustments to energy and irradiance representations, details dynamic QC validation boundaries, confirms the exclusion of wind-specific keys, and outlines the schema changes encapsulated in Alembic Migration `0003`.

---

## 2. Raw Kaggle Column to Canonical Key Mapping Table

The Kaggle dataset comprises four CSV files across two solar plants:
* **Generation Data:** `Plant_1_Generation_Data.csv`, `Plant_2_Generation_Data.csv`
* **Weather Sensor Data:** `Plant_1_Weather_Sensor_Data.csv`, `Plant_2_Weather_Sensor_Data.csv`

The following table specifies the mapping for each raw column to the PlantIQ canonical model:

| Source File(s) | Raw Column Name | Canonical Key / Dimension | Canonical Data Type | Raw Unit | Canonical Target Unit | Ingestion Transform / Scale Factor | Monotonicity & Constraints |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Generation** | `DATE_TIME` | `timestamp` (Dimension) | `TIMESTAMPTZ` (UTC) | String | ISO 8601 UTC | Plant 1: Parse `%d-%m-%Y %H:%M`<br>Plant 2: Parse `%Y-%m-%d %H:%M:%S` | Strictly chronological per device |
| **Generation** | `PLANT_ID` | `plant_id` (Dimension) | `VARCHAR` | Integer ID | Identifier | String coercion / FK lookup (`4135001` $\to$ `surya_a`) | Fixed dimension |
| **Generation** | `SOURCE_KEY` | `device_id` (Dimension) | `VARCHAR` | Alphanumeric | Identifier | Direct 1:1 inverter string identifier | Inverter hardware identity |
| **Generation** | `DC_POWER` | `power_dc` | `FLOAT` | Deci-kW (P1) / kW (P2) | **W** (Watt) | **Plant 1:** `val * 100.0` ($P_{dc} \times 0.1 \times 1000$)<br>**Plant 2:** `val * 1000.0` ($P_{dc} \times 1000$) | Range: $0.0 \dots 1.2 \times \text{rated\_dc}$ |
| **Generation** | `AC_POWER` | `power_ac` | `FLOAT` | kW | **W** (Watt) | `val * 1000.0` (kW $\to$ W) | Range: $0.0 \dots 1.1 \times \text{rated\_ac}$ |
| **Generation** | `DAILY_YIELD` | `energy_ac_daily` | `FLOAT` | kWh | **Wh** (Watt-hour) | `val * 1000.0` (kWh $\to$ Wh) | Daily reset at 00:00; non-decreasing within day |
| **Generation** | `TOTAL_YIELD` | `energy_ac_total` | `FLOAT` | kWh | **Wh** (Watt-hour) | `val * 1000.0` (kWh $\to$ Wh) | Cumulative lifetime; strictly monotonic non-decreasing |
| **Weather** | `DATE_TIME` | `timestamp` (Dimension) | `TIMESTAMPTZ` (UTC) | String | ISO 8601 UTC | Parse `%Y-%m-%d %H:%M:%S` (Plant 1 & 2) | 15-minute standard intervals |
| **Weather** | `PLANT_ID` | `plant_id` (Dimension) | `VARCHAR` | Integer ID | Identifier | String coercion / FK lookup | Fixed dimension |
| **Weather** | `SOURCE_KEY` | `device_id` (Dimension) | `VARCHAR` | Alphanumeric | Identifier | Weather station identifier (`HmiyD2...`, `iq8k7...`) | Weather station hardware identity |
| **Weather** | `AMBIENT_TEMPERATURE` | `temperature_ambient` | `FLOAT` | °C | **°C** (Celsius) | Identity (`1.0`) | Physical Range: $-30.0^\circ\text{C} \dots 60.0^\circ\text{C}$ |
| **Weather** | `MODULE_TEMPERATURE` | `temperature_module` | `FLOAT` | °C | **°C** (Celsius) | Identity (`1.0`) | Physical Range: $-20.0^\circ\text{C} \dots 90.0^\circ\text{C}$ |
| **Weather** | `IRRADIATION` | `irradiance_poa` | `FLOAT` | kW/m² | **W/m²** | `val * 1000.0` (kW/m² $\to$ W/m²) | Range: $0.0 \dots 1500.0 \text{ W/m}^2$; tagged with `approx_ghi` metadata |

### Unmapped / Missing Infrastructure Signals
As established in the empirical profile, the Kaggle datasets omit standard utility solar telemetry signals:
* **Plant Substation Export Revenue Meter:** *No canonical key exists in Kaggle feed.* Plant-level AC power must be synthesized as $\sum_{i=1}^{22} P_{ac, i}$.
* **Combiner Box / String Monitoring ($I_{\text{string}}$):** *No canonical key exists in Kaggle feed.*
* **Inverter Operating Status & Alarms:** *No canonical key exists in Kaggle feed.* Availability is resolved via daytime heuristic ($G > 50 \text{ W/m}^2 \land P_{ac} \approx 0$).
* **Wind Speed / Direction:** *No canonical key exists in Kaggle feed.* Thermal derating relies directly on measured `temperature_module`.
* **DC & AC Voltages / Currents ($V_{dc}, I_{dc}, V_{ac}, I_{ac}$):** *No canonical key exists in Kaggle feed.*

---

## 3. Proposed Additions & Adjustments with Engineering Rationale

### 3.1 `energy_ac_daily` & `energy_ac_total` Mapping and Monotonicity Architecture

In Spec §12.3, energy signals were generically designated as `energy_ac`. The Kaggle dataset necessitates two distinct canonical signals:
1. `energy_ac_daily` (Daily cumulative AC generation counter, resetting at midnight local time).
2. `energy_ac_total` (Cumulative lifetime AC generation register).

#### Physical Monotonicity Rules & Telemetry Ingestion Handling:
* **`energy_ac_daily` Monotonicity Contract:**
  - **Constraint:** Must be monotonically non-decreasing within each calendar day:
    $$\forall t_i, t_{i-1} \in \text{Same Day}: \quad E_{\text{daily}}(t_i) \ge E_{\text{daily}}(t_{i-1})$$
  - **Reset Behavior:** Drops to $0.0$ at the first interval following midnight ($00:00$ or $00:15$).
  - **QC Ingestion Check:** If $E_{\text{daily}}(t_i) < E_{\text{daily}}(t_{i-1})$ during daylight hours ($G > 0$), tag record with `QC_FLAG_DAILY_ENERGY_DROP`.
* **`energy_ac_total` Monotonicity Contract:**
  - **Constraint:** Hardware meter registers must be strictly non-decreasing across the asset's operating lifetime:
    $$\forall t_i > t_{i-1}: \quad E_{\text{total}}(t_i) \ge E_{\text{total}}(t_{i-1})$$
  - **Empirical Findings (Task S1-AI-02):**
    - **Plant 1 (Surya-A):** 100% strictly monotonic (0 negative steps across all 22 inverters over 34 days). Mean deviation between $(\max E_{\text{total}} - \min E_{\text{total}})$ and $E_{\text{daily}}$ is $< 10 \text{ Wh}$.
    - **Plant 2 (Surya-B):** Suffers from 1,162 negative resets and corrupted spikes up to $2.24 \times 10^9 \text{ Wh}$.
* **Authoritative Energy KPI Rule:**
  - **Rule:** Because hardware register rollovers and inverter firmware restarts corrupt cumulative registers (as proved in Plant 2), **Riemann-sum integrated AC power ($\int P_{ac} dt \approx \sum P_{ac} \times \Delta t$) is designated as the primary ground-truth Energy KPI**.
  - `energy_ac_total` is ingested as a distinct signal for auditing and baseline comparison, but is subject to a strict `QC_MONOTONIC_INCREASING` validation filter.

---

### 3.2 `irradiance_poa` vs `irradiance_ghi` Resolution for Ambiguous Sensors

#### The Architectural Dilemma:
In the Kaggle weather data, the irradiance sensor is labeled simply `IRRADIATION`. In Task S1-AI-02:
* Daylight readings reach up to **$1.2217 \text{ kW/m}^2$ ($1221.7 \text{ W/m}^2$)** in Plant 1 and **$1.0988 \text{ kW/m}^2$ ($1098.8 \text{ W/m}^2$)** in Plant 2.
* Terrestrial clear-sky Global Horizontal Irradiance (GHI) rarely exceeds $1000 - 1050 \text{ W/m}^2$. Irradiance exceeding $1100 \text{ W/m}^2$ strongly indicates the sensor is tilted in the **Plane of Array (POA)**.
* However, sensor orientation, tilt angle, and pyranometer azimuth are not documented in the Kaggle metadata, creating physical ambiguity.

#### Evaluation of Options:
1. **Option 1: Introduce a third key `irradiance_unspecified` (Rejected).**
   - *Rationale for Rejection:* Adding `irradiance_unspecified` fragments downstream analytical queries. Every calculation of Performance Ratio (IEC 61724-1 PR), weather-normalized expected power, and degradation rate would have to implement complex conditional fallback logic:
     $$\text{Irradiance} = \text{COALESCE}(\text{irradiance\_poa}, \, \text{irradiance\_ghi}, \, \text{irradiance\_unspecified})$$
   - It introduces schema bloat, weakens typed database constraints, and pollutes feature stores.
2. **Option 2: Map to `irradiance_poa` with a channel-level metadata flag (Recommended & Adopted).**
   - *Rationale:* Utility solar performance analysis fundamentally requires Plane of Array (POA) irradiance to evaluate inverter clipping, DC string efficiency, and temperature-adjusted PR ($PR_{\text{STC}}$). Since the empirical magnitude ($1221.7 \text{ W/m}^2$) matches POA summer values, mapping to `irradiance_poa` ensures immediate compatibility with all solar analytics engines.
   - To preserve data provenance and satisfy auditability, the sensor's physical channel configuration is tagged in the asset metadata store:
     ```json
     {
       "device_id": "HmiyD2TTLFNqkNe",
       "signal_key": "irradiance_poa",
       "sensor_type": "pyranometer",
       "mounting_geometry": "UNKNOWN",
       "approx_ghi": true,
       "poa_assumed": true
     }
     ```
   - When downstream models specifically require horizontal irradiance (e.g. satellite cross-validation or Perez transposition), the pipeline references the `approx_ghi = true` flag to trigger standard reverse-transposition algorithms.

---

### 3.3 Dynamic QC Ingestion Bounds for Rated Capacity Multiples

#### The Problem with Static Bounds:
Standard schema validation typically applies static minimum and maximum thresholds (e.g., `min: 0.0, max: 2000.0`). However, in utility solar:
* A string inverter may have a rated capacity of $50 \text{ kW}$ ($50,000 \text{ W}$).
* A central inverter may have a rated capacity of $1.25 \text{ MW}$ ($1,250,000 \text{ W}$).
* A static upper limit of $2 \text{ MW}$ would completely fail to catch severe over-generation anomalies on a $50 \text{ kW}$ unit, while a limit of $100 \text{ kW}$ would reject all valid data from central inverters.

#### Specification for Dynamic Bound Resolution (Input for Task S2-AI-03):
In the canonical dictionary, fields with dynamic capacity relationships define their validation boundaries as mathematical expressions referencing asset metadata:
* `power_dc`: Bounds = $[0.0, \, 1.20 \times \text{rated\_dc\_w}]$
* `power_ac`: Bounds = $[0.0, \, 1.10 \times \text{rated\_ac\_w}]$

#### Ingestion Pipeline Execution Mechanism:
```
               Raw Telemetry Packet
            [device_id, power_dc, timestamp]
                         │
                         ▼
        ┌───────────────────────────────────┐
        │  Asset Registry Cache (In-Memory)  │
        │  Look up device_id rated_dc_w     │
        └─────────────────┬─────────────────┘
                         │
                         ▼
     Compute Dynamic Range:
     Max Threshold = 1.20 * rated_dc_w
                         │
                         ▼
     ┌───────────────────┴───────────────────┐
     │ power_dc <= Max Threshold?            │
     ├───────────────────┬───────────────────┤
     │ YES               │ NO                │
     ▼                   ▼                   │
   [Valid Ingest]      [QC Flag: RANGE_HIGH] 
                       [Route to Dead-Letter]
```

1. **Asset Metadata Pre-Caching:** At worker startup, the ingestion service loads an in-memory dictionary mapping each `device_id` to its nameplate `rated_dc_w` and `rated_ac_w`.
2. **Evaluation at Parsing Time:** When normalizing `DC_POWER` (scaled to Watts), the ingestion worker evaluates whether:
   $$0.0 \le P_{dc} \le 1.20 \times \text{device.rated\_dc\_w}$$
3. **Threshold Margin Justification:** A $20\%$ DC headroom ($1.20\times$) accounts for the standard DC-to-AC oversizing ratio (ILR / Inverter Loading Ratio typically $1.15 - 1.25$) and high-irradiance cloud-edge reflection events before inverter clipping occurs.
4. **Anomalous Action:** Readings exceeding $1.20 \times \text{rated}$ are flagged with `QC_FLAG_OUT_OF_BOUNDS_HIGH` and logged for engineer inspection.

---

## 4. Explicit Exclusion of Wind-Pack Keys

Spec §12.3 contains candidate telemetry keys for both solar and wind assets. The following wind-specific keys are **explicitly excluded** from the Solar MVP database schema and active ingestion validation rules:

| Wind-Pack Key | Unit | Physical Quantity | Status in Solar MVP | Exclusion Rationale |
| :--- | :--- | :--- | :--- | :--- |
| `wind_speed` | m/s | Anemometer horizontal wind velocity | **Excluded** | No anemometer exists in Kaggle solar stations; thermal model uses module temp. |
| `wind_direction` | deg | Wind vane azimuth | **Excluded** | Irrelevant for non-tracking fixed-tilt solar arrays. |
| `rotor_speed` | rpm | Turbine rotor rotation velocity | **Excluded** | Wind turbine aerodynamic mechanical signal; non-existent on PV assets. |
| `pitch_angle` | deg | Turbine blade aerodynamic pitch angle | **Excluded** | Wind turbine mechanical actuation signal. |
| `yaw_angle` | deg | Nacelle wind tracking azimuth | **Excluded** | Wind turbine mechanical actuation signal. |
| `generator_speed` | rpm | High-speed shaft generator velocity | **Excluded** | Rotating machine signal. |
| `gearbox_temperature` | °C | Main drive-train gearbox oil/bearing temp | **Excluded** | Rotating machine signal. |
| `nacelle_position` | deg | Absolute nacelle compass orientation | **Excluded** | Wind turbine structural signal. |

*Architectural Impact:* Excluding wind keys prevents database table widening, eliminates unneeded nullable columns, simplifies SQL/DuckDB ingestion schemas, and prevents false "missing signal" alerts during solar ingestion runs.

---

## 5. Schema Migration Plan (Alembic Migration 0003)

Rather than altering migration `0002` (which established baseline telemetry tables), all dictionary additions and refinements are encapsulated in a new forward migration:
* **Migration Script:** [`/backend/alembic/versions/0003_canonical_dictionary_solar_adjustments.py`](file:///home/stpl/Desktop/plantiq/backend/alembic/versions/0003_canonical_dictionary_solar_adjustments.py)
* **Target Table:** `canonical_signals`
* **Changes Enacted:**
  1. Register `energy_ac_daily` (Wh) with daily reset metadata.
  2. Register `energy_ac_total` (Wh) with strict lifetime monotonicity constraints.
  3. Register `irradiance_poa` (W/m²) with default `approx_ghi = true` metadata.
  4. Update `power_dc` and `power_ac` with dynamic boundary validation rules (`0..1.2*rated`).
  5. Ensure wind-pack keys remain inactive (`is_active = FALSE`).
  6. Provide full bidirectional rollback support in `downgrade()`.
