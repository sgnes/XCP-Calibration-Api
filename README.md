# XcpCalibrationAPI 

**High-level calibration and measurement helper for XCP + A2L**

## Overview

`XcpCalibrationAPI` is a convenience layer on top of your `XcpCanMaster` and `A2LModel` that makes common calibration and measurement tasks simple and robust:

- Connect/disconnect XCP session
- Resolve measurement/characteristic by name
- Read measurement values (raw and physical) using A2L conversion rules
- Read/write scalar `VALUE` characteristics in physical units
- Read/write raw memory addresses via XCP
- Apply `COMPU_METHOD` conversions (`IDENTICAL`, `LINEAR`, `RAT_FUNC`)
- Auto-select XCP address extension based on A2L `MEMORY_SEGMENT` if available
- Endianness selectable (`"little"` by default)

This library assumes a little-endian target by default and focuses on scalar `VALUE` characteristics. Support for `VAL_BLK`, `CURVE`, `MAP`, etc., can be added using the raw memory helpers.

## Features

- Simple API to read measurements and characteristics:
  - `read_measurement(name)` ➜ returns raw and physical values
  - `read_characteristic(name)` ➜ returns raw and physical values
  - `write_characteristic(name, physical_value)` ➜ writes using A2L’s `COMPU_METHOD`
- Raw memory access:
  - `read_raw(address, size)` / `write_raw(address, data)`
- `COMPU_METHOD` support:
  - `IDENTICAL` (identity)
  - `LINEAR` \(y = a \cdot x + b\)
  - `RAT_FUNC` \(y = \frac{a x + b}{c x + d} [+ e]\)
  - Register custom conversions per method name via `register_custom_compu`
- Address extension resolution:
  - Uses `a2l_model.memory_segments` when available
  - Falls back to `default_addr_ext`

## Requirements

- `XcpCanMaster` (your XCP transport/command implementation)
- `A2LModel` with parsed A2L data (measurements, characteristics, compu methods, record layouts, memory segments)
- Python 3.8+ recommended

## Installation

Place the `XcpCalibrationAPI` module alongside your `XcpCanMaster` and `A2LModel` implementations and import:

```python
from xcp_master import XcpCanMaster
from a2l_parser import A2LModel
from xcp_calibration_api import XcpCalibrationAPI  # rename to your actual file name
```

## Quick Start

```python
from xcp_master import XcpCanMaster
from a2l_parser import A2LModel
from xcp_calibration_api import XcpCalibrationAPI

# 1) Build the XCP master (configure CAN channel, XCP settings, etc.)
xcp = XcpCanMaster(channel=0, bitrate=500000, ...)

# 2) Load/parse your A2L file
a2l = A2LModel.parse_file("my_ecu.a2l")  # adapt to your parser API

# 3) Create the high-level calibration API
api = XcpCalibrationAPI(xcp=xcp, a2l_model=a2l, default_addr_ext=0, byteorder="little")

# 4) Connect to ECU
api.connect()

# 5) Read a measurement (raw+physical)
m = api.read_measurement("ENG_SPEED")
print("ENG_SPEED raw:", m["raw_value"], "phys:", m["physical_value"], m["unit"])

# 6) Read a characteristic (raw+physical)
c = api.read_characteristic("Idle_Target_RPM")
print("Idle_Target_RPM phys:", c["physical_value"])

# 7) Write a characteristic in physical units
api.write_characteristic("Idle_Target_RPM", 800.0)

# 8) Raw memory access (advanced)
addr = 0x123456
data = api.read_raw(address=addr, size=4)
print("Raw 0x123456:", data.hex())
api.write_raw(address=addr, data=b"\x01\x02\x03\x04")

# 9) Disconnect
api.disconnect()
```

## API Reference

### Session

- `connect(mode: int = 0x00) -> Dict[str, Any]`
  - Connects the XCP session and reads communication mode info.
- `disconnect() -> None`
  - Disconnects the XCP session.
- `switch_cal_page(page: int, mode: int = 0, segment: int = 0) -> Dict[str, Any]`
  - Switches calibration page as supported by the slave.

### Resolution Helpers

- `find_measurement(name: str) -> Optional[Measurement]`
  - Returns the measurement entry by name.
- `find_characteristic(name: str) -> Optional[Characteristic]`
  - Returns the characteristic entry by name.
- `resolve_addr_ext(address: int) -> int`
  - Determines address extension from `memory_segments` if available, otherwise returns `default_addr_ext`.

### Data Type Helpers

- `_datatype_to_size(datatype: str) -> Optional[int]`
- `_is_float_datatype(datatype: str) -> bool`
- `_is_signed_datatype(datatype: str) -> bool`
- `_pack_from_int(datatype: str, value: int) -> bytes`
- `_unpack_to_int_or_float(datatype: str, data: bytes) -> float | int`
- `_infer_value_datatype_from_record_layout(rl_name: Optional[str]) -> Optional[str>`
- `_saturate_to_type_range(value: int, datatype: str) -> int`

These internal helpers infer sizes, signedness, and packing/unpacking logic using ASAP2 tokens such as `UBYTE`, `UWORD`, `UDWORD`, `FLOAT32_IEEE`, etc.

### COMPU Utilities

- `register_custom_compu(compu_name: str, to_phys: Callable[[float], float], to_raw: Callable[[float], float])`
  - Registers a custom pair of conversion functions for a given `COMPU_METHOD` name.
- `_apply_compu_to_phys(compu_name: Optional[str], raw_val: float | int) -> float | int`
- `_apply_compu_to_raw(compu_name: Optional[str], phys_val: float | int) -> float | int`

By default, the following methods are supported:
- `IDENTICAL`: identity
- `LINEAR`: \(y = a \cdot x + b\)
- `RAT_FUNC`: \(y = \frac{a x + b}{c x + d} [+ e]\)
  - Inverse implemented for the 4-coefficient form \((a, b, c, d)\). For 5-coefficient form \([+ e]\), only forward conversion is applied by default. Register a custom inverse if needed.

### Raw Memory

- `read_raw(address: int, size: int, addr_ext: Optional[int] = None, timeout: Optional[float] = None) -> bytes`
  - Reads `size` bytes from `address` using XCP, optionally with `addr_ext`.
- `write_raw(address: int, data: bytes, addr_ext: Optional[int] = None, timeout: Optional[float] = None) -> None`
  - Writes `data` to `address` using XCP.

### Measurement

- `read_measurement(name: str, addr_ext: Optional[int] = None, timeout: Optional[float] = None) -> Dict[str, Any]`
  - Returns a dictionary including:
    - `name`, `address`, `addr_ext`
    - `datatype`, `raw_bytes`, `raw_value`
    - `physical_value`, `unit`

Convenience:
- `read_measurement_raw_value(name: str, addr_ext: Optional[int] = None) -> int | float`
- `read_measurement_phys(name: str, addr_ext: Optional[int] = None) -> float | int`

### Characteristic (Scalar VALUE)

- `read_characteristic(name: str, addr_ext: Optional[int] = None, timeout: Optional[float] = None) -> Dict[str, Any]`
  - Returns:
    - `name`, `address`, `addr_ext`
    - `char_type`, `record_layout`
    - `raw_bytes`, `raw_value`
    - `physical_value`, `unit`, `datatype`
  - Uses `record_layout` heuristics to infer storage datatype (falls back to `UDWORD`).
- `write_characteristic(name: str, physical_value: float | int, addr_ext: Optional[int] = None, timeout: Optional[float] = None, clamp_limits: bool = True) -> None`
  - Converts physical value to raw based on `COMPU_METHOD`, clamps to `lower_limit`/`upper_limit` if available, then writes.

Convenience:
- `read_characteristic_phys(name: str, addr_ext: Optional[int] = None) -> float | int`
- `write_characteristic_phys(name: str, phys_value: float | int, addr_ext: Optional[int] = None) -> None`

## Custom COMPU Example

```python
def temp_to_phys(raw: float) -> float:
    # example: Kelvin to Celsius
    return raw - 273.15

def temp_to_raw(phys: float) -> float:
    return phys + 273.15

api.register_custom_compu("TEMP_K_TO_C", temp_to_phys, temp_to_raw)

# Assuming a characteristic uses COMPU_METHOD named "TEMP_K_TO_C"
api.write_characteristic("Coolant_Temp_Target", 85.0)  # writes ~358.15 raw
val = api.read_characteristic("Coolant_Temp_Target")["physical_value"]  # returns 85.0
```

## Integration with a Test Runner (Optional)

You can integrate `XcpCalibrationAPI` into a higher-level test device class (e.g., `TestDevice`) that also includes a UDS client for diagnostics. Typical operations:

- `ChangeEcuCalib` ➜ `write_characteristic`
- `GetEcuVarValue` ➜ `read_characteristic` + tolerance check
- `SendDiagcReqToEcu` ➜ via your UDS `Client` (e.g., `udsoncan`)
- `GetCanBusSIgnalValue` ➜ your `signal_reader` callback (DBC decode + CAN subscription)
- `ReConnectCCP` ➜ `disconnect()` then `connect()`

## Assumptions and Limitations

- **Endianness**: Defaults to `"little"`. Set `byteorder="big"` if your target is big-endian.
- **COMPU_METHODs**: Built-in support for `IDENTICAL`, `LINEAR`, `RAT_FUNC` forward conversion and limited inverse. Register custom converters for complex methods.
- **Record layout inference**: Heuristic parsing of `RECORD_LAYOUT` to infer datatype. If inference fails, defaults to `UDWORD` (4 bytes unsigned). Adjust if your A2L uses specialized layouts.
- **Scalar `VALUE` focus**: Operations are optimized for scalar characteristics. For arrays, curves, maps, or blocks, use raw memory helpers or extend the API.
- **Address extension**: Requires `a2l_model.memory_segments` populated with `address`, `size`, and `segment_info.address_extension`. Falls back to `default_addr_ext` otherwise.

## Troubleshooting

- Missing measurement/characteristic:
  - Ensure the name exists in the A2L and matches exactly.
- Wrong physical values:
  - Verify the correct `COMPU_METHOD` is referenced and coefficients populated.
  - Check endianness (`byteorder`).
- Write fails or corrupts data:
  - Confirm the inferred storage datatype is correct. If not, specify a custom process or adjust `RECORD_LAYOUT` parsing.
  - Ensure limits and conversion are valid (no division by zero, etc.).
- Address extension mismatch:
  - Populate `memory_segments` in A2L or set `default_addr_ext` appropriately.

## Best Practices

- Always `connect()` before any operation and `disconnect()` after.
- Use `read_measurement` for live data and `read_characteristic` for calibration parameters.
- Register custom converters when your `COMPU_METHOD` is non-linear or not covered by built-ins.
- Validate limits (`lower_limit`, `upper_limit`) and units in A2L to avoid invalid writes.

## License

This code is provided as-is for integration with your XCP and A2L tooling. Adapt to your project’s license and constraints.

## Changelog

- Initial version:
  - Measurement/characteristic read/write
  - COMPU conversion support
  - Raw memory helpers
  - Address extension auto-resolution
  - Endianness control

If you need additional examples (e.g., DAQ/STM measurement streaming, block writes, or advanced COMPU methods), let me know and I can extend the documentation and API.