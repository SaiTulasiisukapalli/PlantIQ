"""Production-grade unit conversion module for PlantIQ MVP.

Task: S1-AI-03 Part B
Provides:
- Strict unit normalization supporting unicode aliases, exponents, and case variations.
- Registry of conversion callables for energy, power, irradiance, and temperature.
- Vectorized `convert` function supporting both scalars (float, int) and Polars Series.
- Typed `UnknownConversionError` for unmapped units or cross-dimensional conversions.
"""

from __future__ import annotations

import re
from typing import Any, Callable, Dict, Optional, Tuple, TypeVar, Union, overload
import polars as pl

T_Value = TypeVar("T_Value", float, int, pl.Series)
ConversionCallable = Callable[[Any], Any]


class UnknownConversionError(ValueError):
    """Raised when an unrecognized unit or an unsupported conversion is requested."""

    def __init__(self, from_unit: str, to_unit: str, reason: str = "") -> None:
        self.from_unit = from_unit
        self.to_unit = to_unit
        self.reason = reason
        msg = f"Cannot convert from '{from_unit}' to '{to_unit}'"
        if reason:
            msg += f": {reason}"
        super().__init__(msg)


# Canonical base units per physical dimension
DIM_POWER = "power"
DIM_ENERGY = "energy"
DIM_IRRADIANCE = "irradiance"
DIM_TEMPERATURE = "temperature"

# Map canonical units to their physical dimensions
CANONICAL_UNITS: Dict[str, str] = {
    # Power (base: W)
    "W": DIM_POWER,
    "kW": DIM_POWER,
    "MW": DIM_POWER,
    "GW": DIM_POWER,
    # Energy (base: Wh)
    "Wh": DIM_ENERGY,
    "kWh": DIM_ENERGY,
    "MWh": DIM_ENERGY,
    "GWh": DIM_ENERGY,
    # Irradiance (base: W/m²)
    "W/m²": DIM_IRRADIANCE,
    "kW/m²": DIM_IRRADIANCE,
    # Temperature (base: degC)
    "degC": DIM_TEMPERATURE,
    "degF": DIM_TEMPERATURE,
    "K": DIM_TEMPERATURE,
}

# Alias dictionary mapping variants to canonical unit strings
_UNIT_ALIASES: Dict[str, str] = {
    # Power: W
    "w": "W",
    "watt": "W",
    "watts": "W",
    # Power: kW
    "kw": "kW",
    "kilowatt": "kW",
    "kilowatts": "kW",
    # Power: MW
    "mw": "MW",
    "megawatt": "MW",
    "megawatts": "MW",
    # Power: GW
    "gw": "GW",
    "gigawatt": "GW",
    "gigawatts": "GW",
    # Energy: Wh
    "wh": "Wh",
    "whr": "Wh",
    "watt-hour": "Wh",
    "watthour": "Wh",
    "watt_hour": "Wh",
    "watt-hours": "Wh",
    # Energy: kWh
    "kwh": "kWh",
    "kwhr": "kWh",
    "kilowatt-hour": "kWh",
    "kilowatthour": "kWh",
    "kilowatt_hour": "kWh",
    "kilowatt-hours": "kWh",
    # Energy: MWh
    "mwh": "MWh",
    "mwhr": "MWh",
    "megawatt-hour": "MWh",
    "megawatthour": "MWh",
    "megawatt_hour": "MWh",
    "megawatt-hours": "MWh",
    # Energy: GWh
    "gwh": "GWh",
    "gwhr": "GWh",
    "gigawatt-hour": "GWh",
    "gigawatthour": "GWh",
    "gigawatt_hour": "GWh",
    # Irradiance: W/m²
    "w/m2": "W/m²",
    "w/m^2": "W/m²",
    "w/m²": "W/m²",
    "w / m2": "W/m²",
    "w / m^2": "W/m²",
    "w / m²": "W/m²",
    "watt/m2": "W/m²",
    "watt/m^2": "W/m²",
    "watt/m²": "W/m²",
    "watts/m2": "W/m²",
    "watts/m^2": "W/m²",
    "watts/m²": "W/m²",
    # Irradiance: kW/m²
    "kw/m2": "kW/m²",
    "kw/m^2": "kW/m²",
    "kw/m²": "kW/m²",
    "kw / m2": "kW/m²",
    "kw / m^2": "kW/m²",
    "kw / m²": "kW/m²",
    "kilowatt/m2": "kW/m²",
    "kilowatt/m^2": "kW/m²",
    "kilowatt/m²": "kW/m²",
    # Temperature: Celsius
    "c": "degC",
    "degc": "degC",
    "deg_c": "degC",
    "°c": "degC",
    "celsius": "degC",
    "centigrade": "degC",
    # Temperature: Fahrenheit
    "f": "degF",
    "degf": "degF",
    "deg_f": "degF",
    "°f": "degF",
    "fahrenheit": "degF",
    # Temperature: Kelvin
    "k": "K",
    "kelvin": "K",
}


def normalize_unit(unit_str: str) -> str:
    """Normalize raw unit string to standard canonical representation.

    Handles whitespace stripping, exponents (^2 -> ²), unicode symbols,
    and case normalization.

    Raises:
        UnknownConversionError: If unit string cannot be matched to a known unit.
    """
    if not isinstance(unit_str, str):
        raise UnknownConversionError(
            str(unit_str), "", reason=f"Unit must be a string, got {type(unit_str).__name__}"
        )

    cleaned = unit_str.strip()
    if not cleaned:
        raise UnknownConversionError(unit_str, "", reason="Unit string cannot be empty")

    # Direct canonical match
    if cleaned in CANONICAL_UNITS:
        return cleaned

    # Normalized lookup key
    norm_key = cleaned.lower()
    # Normalize exponents and degree symbols
    norm_key = re.sub(r"\s+", " ", norm_key)
    norm_key = norm_key.replace("degrees ", "deg").replace("degree ", "deg")
    norm_key = norm_key.replace("deg ", "deg")

    if norm_key in _UNIT_ALIASES:
        return _UNIT_ALIASES[norm_key]

    raise UnknownConversionError(
        unit_str, "", reason=f"Unrecognized unit '{unit_str}'"
    )


# Pairwise callable registry for fast execution
# Keys: (canonical_from_unit, canonical_to_unit)
_CONVERSION_REGISTRY: Dict[Tuple[str, str], ConversionCallable] = {}


def register_converter(
    from_unit: str,
    to_unit: str,
    converter: ConversionCallable,
) -> None:
    """Register a custom conversion callable between two canonical units."""
    norm_from = normalize_unit(from_unit)
    norm_to = normalize_unit(to_unit)
    _CONVERSION_REGISTRY[(norm_from, norm_to)] = converter


# ----------------------------------------------------------------------
# Core Conversion Callables (Scalars and Polars Series Vectorized)
# ----------------------------------------------------------------------

def _kW_to_W(val: Any) -> Any:
    return val * 1000.0


def _W_to_kW(val: Any) -> Any:
    return val / 1000.0


def _MW_to_W(val: Any) -> Any:
    return val * 1_000_000.0


def _W_to_MW(val: Any) -> Any:
    return val / 1_000_000.0


def _MWh_to_kWh(val: Any) -> Any:
    return val * 1000.0


def _kWh_to_MWh(val: Any) -> Any:
    return val / 1000.0


def _Wh_to_kWh(val: Any) -> Any:
    return val / 1000.0


def _kWh_to_Wh(val: Any) -> Any:
    return val * 1000.0


def _kWm2_to_Wm2(val: Any) -> Any:
    return val * 1000.0


def _Wm2_to_kWm2(val: Any) -> Any:
    return val / 1000.0


def _Wm2_to_Wm2(val: Any) -> Any:
    return val


def _degF_to_degC(val: Any) -> Any:
    return (val - 32.0) * (5.0 / 9.0)


def _degC_to_degF(val: Any) -> Any:
    return (val * (9.0 / 5.0)) + 32.0


def _K_to_degC(val: Any) -> Any:
    return val - 273.15


def _degC_to_K(val: Any) -> Any:
    return val + 273.15


def _degF_to_K(val: Any) -> Any:
    return (val - 32.0) * (5.0 / 9.0) + 273.15


def _K_to_degF(val: Any) -> Any:
    return (val - 273.15) * (9.0 / 5.0) + 32.0


# Populate required pairwise converters
register_converter("kW", "W", _kW_to_W)
register_converter("W", "kW", _W_to_kW)
register_converter("MW", "W", _MW_to_W)
register_converter("W", "MW", _W_to_MW)
register_converter("MW", "kW", lambda val: val * 1000.0)
register_converter("kW", "MW", lambda val: val / 1000.0)
register_converter("GW", "W", lambda val: val * 1_000_000_000.0)
register_converter("W", "GW", lambda val: val / 1_000_000_000.0)

register_converter("MWh", "kWh", _MWh_to_kWh)
register_converter("kWh", "MWh", _kWh_to_MWh)
register_converter("Wh", "kWh", _Wh_to_kWh)
register_converter("kWh", "Wh", _kWh_to_Wh)
register_converter("Wh", "Wh", lambda val: val)
register_converter("kWh", "kWh", lambda val: val)
register_converter("MWh", "Wh", lambda val: val * 1_000_000.0)
register_converter("Wh", "MWh", lambda val: val / 1_000_000.0)
register_converter("GWh", "kWh", lambda val: val * 1_000_000.0)
register_converter("kWh", "GWh", lambda val: val / 1_000_000.0)

register_converter("kW/m²", "W/m²", _kWm2_to_Wm2)
register_converter("W/m²", "kW/m²", _Wm2_to_kWm2)
register_converter("W/m²", "W/m²", _Wm2_to_Wm2)
register_converter("kW/m²", "kW/m²", lambda val: val)

register_converter("degF", "degC", _degF_to_degC)
register_converter("degC", "degF", _degC_to_degF)
register_converter("K", "degC", _K_to_degC)
register_converter("degC", "K", _degC_to_K)
register_converter("degF", "K", _degF_to_K)
register_converter("K", "degF", _K_to_degF)
register_converter("degC", "degC", lambda val: val)
register_converter("degF", "degF", lambda val: val)
register_converter("K", "K", lambda val: val)


def get_converter(from_unit: str, to_unit: str) -> ConversionCallable:
    """Retrieve the callable that converts values from from_unit to to_unit.

    Raises:
        UnknownConversionError: If units are unrecognized or dimensionally incompatible.
    """
    canon_from = normalize_unit(from_unit)
    canon_to = normalize_unit(to_unit)

    # Identity conversion
    if canon_from == canon_to:
        return lambda val: val

    dim_from = CANONICAL_UNITS.get(canon_from)
    dim_to = CANONICAL_UNITS.get(canon_to)

    if dim_from != dim_to:
        raise UnknownConversionError(
            from_unit,
            to_unit,
            reason=f"Incompatible physical dimensions ('{dim_from}' vs '{dim_to}')",
        )

    pair = (canon_from, canon_to)
    if pair in _CONVERSION_REGISTRY:
        return _CONVERSION_REGISTRY[pair]

    raise UnknownConversionError(
        from_unit,
        to_unit,
        reason=f"No direct or transitive converter registered between '{canon_from}' and '{canon_to}'",
    )


# ----------------------------------------------------------------------
# Public Vectorized Interface
# ----------------------------------------------------------------------

@overload
def convert(value: Union[float, int], from_unit: str, to_unit: str) -> float: ...


@overload
def convert(value: pl.Series, from_unit: str, to_unit: str) -> pl.Series: ...


def convert(
    value: Union[float, int, pl.Series],
    from_unit: str,
    to_unit: str,
) -> Union[float, pl.Series]:
    """Convert value(s) from `from_unit` to `to_unit`.

    Vectorized implementation: operates on both scalars (float, int) and Polars Series.
    For Polars Series, performs vector math directly at native speed, preserving series
    name, data types, and null semantics without python-level loops.

    Args:
        value: Numeric scalar (float/int) or a Polars Series.
        from_unit: Source unit string (e.g., 'kW', 'w/m2', '°F').
        to_unit: Target unit string (e.g., 'W', 'W/m²', 'degC').

    Returns:
        Converted scalar float or Polars Series.

    Raises:
        UnknownConversionError: If any unit is invalid or dimensions are incompatible.
    """
    fn = get_converter(from_unit, to_unit)

    if isinstance(value, pl.Series):
        res = fn(value)
        # Preserve original series name
        if isinstance(res, pl.Series):
            return res.alias(value.name)
        return pl.Series(value.name, res)

    if isinstance(value, (int, float)):
        return float(fn(value))

    raise TypeError(
        f"Unsupported value type '{type(value).__name__}'. Expected float, int, or polars.Series."
    )
