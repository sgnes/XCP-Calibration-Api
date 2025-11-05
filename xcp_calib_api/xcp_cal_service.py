#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations
from typing import Literal, Optional, Dict, Any, Tuple, Callable, List
import struct

from xcp_can_master.xcp_master import XcpCanMaster
from a2lparser.a2l_parser import A2LModel, Measurement, Characteristic,RecordLayout, CompuMethod

# Import your existing classes/types
# from a2l_parser_module import A2LModel, Measurement, Characteristic, RecordLayout, CompuMethod, MemorySegment
# from xcp_can_master import XcpCanMaster

# If you place this file next to the provided A2LParser/XcpCanMaster implementation,
# just import directly:
# from a2l_parser import A2LModel, Measurement, Characteristic, RecordLayout, CompuMethod, MemorySegment
# from xcp_can_master import XcpCanMaster


class XcpCalibrationAPI:
    """
    High-level convenience layer on top of XcpCanMaster and A2LParser model.

    Features:
    - Connect/disconnect convenience
    - Resolve measurement/characteristic by name
    - Read measurement (raw + physical)
    - Read/write scalar characteristic VALUE
    - Read/write raw memory address
    - COMPU_METHOD conversions (IDENTICAL, LINEAR, RAT_FUNC)
    - Address extension auto-resolution from MEMORY_SEGMENT if available

    Notes/assumptions:
    - Little-endian target.
    - Limited COMPU_METHOD support: IDENTICAL (identity), LINEAR (a*x + b), RAT_FUNC ((a*x + b)/(c*x + d) [+ e]).
      Inverse for LINEAR; for RAT_FUNC, inverse is only implemented for 4-coeff form (a,b,c,d). For more complex methods,
      you can register custom conversion hooks.
    - Characteristic write/read focuses on scalar VALUE-type characteristics. For VAL_BLK/CURVE/MAP, use raw helpers or extend.
    """

    def __init__(
        self,
        xcp: XcpCanMaster,
        a2l_model: A2LModel,
        default_addr_ext: int = 0,
        byteorder: Literal['little', 'big'] = "little"
    ):
        self.xcp = xcp
        self.byteorder = byteorder
        self.a2l = a2l_model
        self.default_addr_ext = default_addr_ext
        self._struct_prefix = "<" if byteorder == "little" else ">"

        # Optional custom converters: name -> (to_phys(raw), to_raw(phys))
        self.custom_compu: Dict[str, Tuple[Callable[[float], float], Callable[[float], float]]] = {}

        # Build quick index
        self._meas_by_name: Dict[str, Measurement] = {m.name: m for m in (a2l_model.measurements or [])}
        self._char_by_name: Dict[str, Characteristic] = {c.name: c for c in (a2l_model.characteristics or [])}
        self._compu_by_name: Dict[str, CompuMethod] = {cm.name: cm for cm in (a2l_model.compu_methods or [])}
        self._rl_by_name: Dict[str, RecordLayout] = {rl.name: rl for rl in (a2l_model.record_layouts or [])}

    # ------------ Session convenience ------------
    def connect(self, mode: int = 0x00) -> Dict[str, Any]:
        info = self.xcp.connect(mode=mode)
        _ = self.xcp.get_comm_mode_info()
        return info

    def switch_cal_page(self, page:int, mode:int=0, segment: int=0):
        info = self.xcp.set_cal_page(mode=mode, segment=segment, page=page)
        return info

    def disconnect(self):
        self.xcp.disconnect()

    # ------------ Resolution helpers ------------
    def find_measurement(self, name: str) -> Optional[Measurement]:
        return self._meas_by_name.get(name)

    def find_characteristic(self, name: str) -> Optional[Characteristic]:
        return self._char_by_name.get(name)

    def resolve_addr_ext(self, address: int) -> int:
        """
        Try to auto-select address extension by finding the MEMORY_SEGMENT that contains the address.
        If found and segment_info.address_extension is set, return it. Otherwise return self.default_addr_ext.
        """
        try:
            segs: List["MemorySegment"] = self.a2l.memory_segments or []
        except Exception:
            return self.default_addr_ext

        for seg in segs:
            if seg.address is None or seg.size is None:
                continue
            lo = int(seg.address)
            hi = lo + int(seg.size)
            if lo <= address < hi:
                if seg.segment_info and seg.segment_info.address_extension is not None:
                    return int(seg.segment_info.address_extension)
                break
        return self.default_addr_ext

    # ------------ Data type helpers ------------
    @staticmethod
    def _datatype_to_size(datatype: str) -> Optional[int]:
        if not datatype:
            return None
        dt = datatype.upper()
        # Common ASAP2 names + synonyms
        map_sz = {
            "UBYTE": 1, "SBYTE": 1, "U8": 1, "S8": 1, "BYTE": 1,
            "UWORD": 2, "SWORD": 2, "U16": 2, "S16": 2, "WORD": 2,
            "UDWORD": 4, "SDWORD": 4, "ULONG": 4, "SLONG": 4, "U32": 4, "S32": 4, "LONG": 4,
            "U64": 8, "S64": 8, "A_UINT64": 8, "A_INT64": 8, "QWORD": 8,
            "FLOAT32_IEEE": 4, "FLOAT64_IEEE": 8,
            "BOOLEAN": 1, "BOOL": 1,
        }
        return map_sz.get(dt)

    @staticmethod
    def _is_float_datatype(datatype: str) -> bool:
        if not datatype:
            return False
        dt = datatype.upper()
        return dt in ("FLOAT32_IEEE", "FLOAT64_IEEE")

    @staticmethod
    def _is_signed_datatype(datatype: str) -> bool:
        if not datatype:
            return False
        dt = datatype.upper()
        return dt in ("SBYTE", "S8", "SWORD", "S16", "SDWORD", "SLONG", "S32", "S64", "A_INT64", "LONG")

    def _pack_from_int(self, datatype: str, value: int) -> bytes:
        dt = datatype.upper()
        size = XcpCalibrationAPI._datatype_to_size(dt)
        if size is None:
            # Fallback: 4-byte unsigned
            return int(value).to_bytes(4, self.byteorder, signed=False)
        if dt in ("SBYTE", "S8"):
            return int(value).to_bytes(1, self.byteorder, signed=True)
        if dt in ("UBYTE", "U8", "BOOLEAN", "BOOL", "BYTE"):
            return int(value).to_bytes(1, self.byteorder, signed=False)
        if dt in ("SWORD", "S16"):
            return int(value).to_bytes(2, self.byteorder, signed=True)
        if dt in ("UWORD", "U16", "WORD"):
            return int(value).to_bytes(2, self.byteorder, signed=False)
        if dt in ("SDWORD", "SLONG", "S32", "LONG"):
            return int(value).to_bytes(4, self.byteorder, signed=True)
        if dt in ("UDWORD", "ULONG", "U32"):
            return int(value).to_bytes(4, self.byteorder, signed=False)
        if dt in ("S64", "A_INT64"):
            return int(value).to_bytes(8, self.byteorder, signed=True)
        if dt in ("U64", "A_UINT64", "QWORD"):
            return int(value).to_bytes(8, self.byteorder, signed=False)
        if dt == "FLOAT32_IEEE":
            return struct.pack(self._struct_prefix + "f", float(value))
        if dt == "FLOAT64_IEEE":
            return struct.pack(self._struct_prefix + "d", float(value))
        # Fallback
        return int(value).to_bytes(size, self.byteorder, signed=False)

    def _unpack_to_int_or_float(self, datatype: str, data: bytes) -> float | int:
        dt = datatype.upper()
        if dt in ("SBYTE", "S8"):
            return int.from_bytes(data[:1], self.byteorder, signed=True)
        if dt in ("UBYTE", "U8", "BOOLEAN", "BOOL", "BYTE"):
            return int.from_bytes(data[:1], self.byteorder, signed=False)
        if dt in ("SWORD", "S16"):
            return int.from_bytes(data[:2], self.byteorder, signed=True)
        if dt in ("UWORD", "U16", "WORD"):
            return int.from_bytes(data[:2], self.byteorder, signed=False)
        if dt in ("SDWORD", "SLONG", "S32", "LONG"):
            return int.from_bytes(data[:4], self.byteorder, signed=True)
        if dt in ("UDWORD", "ULONG", "U32"):
            return int.from_bytes(data[:4], self.byteorder, signed=False)
        if dt in ("S64", "A_INT64"):
            return int.from_bytes(data[:8], self.byteorder, signed=True)
        if dt in ("U64", "A_UINT64", "QWORD"):
            return int.from_bytes(data[:8], self.byteorder, signed=False)
        if dt == "FLOAT32_IEEE":
            return struct.unpack(self._struct_prefix + "f", data[:4])[0]
        if dt == "FLOAT64_IEEE":
            return struct.unpack(self._struct_prefix + "d", data[:8])[0]
        # Fallback assume unsigned
        return int.from_bytes(data, self.byteorder, signed=False)

    def _infer_value_datatype_from_record_layout(self, rl_name: Optional[str]) -> Optional[str]:
        """
        Attempts to extract the ASAP2 storage datatype token for a VALUE characteristic
        from the RECORD_LAYOUT's entries.
        Returns the datatype token string (e.g., 'UWORD', 'FLOAT32_IEEE') if found.
        """
        if not rl_name:
            return None
        rl = self._rl_by_name.get(rl_name)
        if not rl or not rl.entries:
            return None
        known = {
            "UBYTE", "SBYTE", "U8", "S8", "BYTE",
            "UWORD", "SWORD", "U16", "S16", "WORD",
            "UDWORD", "SDWORD", "ULONG", "SLONG", "U32", "S32", "LONG",
            "U64", "S64", "A_UINT64", "A_INT64", "QWORD",
            "FLOAT32_IEEE", "FLOAT64_IEEE",
            "BOOLEAN", "BOOL",
        }
        for ln in rl.entries:
            toks = [t.strip().upper() for t in ln.split()]
            for t in toks:
                if t in known:
                    return t
        return None

    def _saturate_to_type_range(self, value: int, datatype: str) -> int:
        size = self._datatype_to_size(datatype) or 4
        signed = self._is_signed_datatype(datatype)
        if self._is_float_datatype(datatype):
            return value  # not used for floats
        if signed:
            min_v = -(1 << (8*size - 1))
            max_v = (1 << (8*size - 1)) - 1
        else:
            min_v = 0
            max_v = (1 << (8*size)) - 1
        return max(min_v, min(max_v, int(value)))
    # ------------ COMPU utilities ------------
    def register_custom_compu(self, compu_name: str, to_phys: Callable[[float], float], to_raw: Callable[[float], float]):
        self.custom_compu[compu_name] = (to_phys, to_raw)

    def _apply_compu_to_phys(self, compu_name: Optional[str], raw_val: float | int) -> float | int:
        if not compu_name:
            return raw_val
        if compu_name in self.custom_compu:
            return self.custom_compu[compu_name][0](float(raw_val))
        cm = self._compu_by_name.get(compu_name)
        if not cm:
            return raw_val
        mtype = (cm.method_type or "").upper()
        coeffs = cm.coeffs or []
        # IDENTICAL
        if mtype == "IDENTICAL":
            return raw_val
        # LINEAR: y = a*x + b
        if mtype == "LINEAR" and len(coeffs) >= 2:
            a, b = coeffs[0], coeffs[1]
            return a * float(raw_val) + b
        # RAT_FUNC: y = (a*x + b)/(c*x + d) [+ e]
        if mtype == "RAT_FUNC" and len(coeffs) >= 4:
            a, b, c, d = coeffs[0], coeffs[1], coeffs[2], coeffs[3]
            y = (a * float(raw_val) + b) / (c * float(raw_val) + d)
            if len(coeffs) >= 5:
                y += coeffs[4]
            return y
        # Default
        return raw_val

    def _apply_compu_to_raw(self, compu_name: Optional[str], phys_val: float | int) -> float | int:
        if not compu_name:
            return phys_val
        if compu_name in self.custom_compu:
            return self.custom_compu[compu_name][1](float(phys_val))
        cm = self._compu_by_name.get(compu_name)
        if not cm:
            return phys_val
        mtype = (cm.method_type or "").upper()
        coeffs = cm.coeffs or []
        if mtype == "IDENTICAL":
            return phys_val
        if mtype == "LINEAR" and len(coeffs) >= 2:
            a, b = coeffs[0], coeffs[1]
            if a == 0:
                raise ZeroDivisionError("Cannot invert LINEAR compu with a == 0")
            return (float(phys_val) - b) / a
        if mtype == "RAT_FUNC" and len(coeffs) >= 4:
            a, b, c, d = coeffs[0], coeffs[1], coeffs[2], coeffs[3]
            y = float(phys_val)
            denom = (y * c) - a
            if denom == 0:
                raise ZeroDivisionError("RAT_FUNC inverse undefined: (y*c - a) == 0")
            return (b - y * d) / denom
        return phys_val

    # ------------ Record layout inference (scalar VALUE) ------------
    def _infer_value_size_from_record_layout(self, rl_name: Optional[str]) -> Optional[int]:
        """
        Tries to infer the underlying storage size for VALUE characteristics from RECORD_LAYOUT entries.
        This is heuristic: scans tokens for a known data type token.
        """
        if not rl_name:
            return None
        rl = self._rl_by_name.get(rl_name)
        if not rl or not rl.entries:
            return None
        known_types = {
            "UBYTE": 1, "SBYTE": 1, "U8": 1, "S8": 1,
            "UWORD": 2, "SWORD": 2, "U16": 2, "S16": 2,
            "UDWORD": 4, "SDWORD": 4, "ULONG": 4, "SLONG": 4, "U32": 4, "S32": 4,
            "FLOAT32_IEEE": 4, "FLOAT64_IEEE": 8,
        }
        for ln in rl.entries:
            toks = [t.strip().upper() for t in ln.split()]
            for t in toks:
                if t in known_types:
                    return known_types[t]
        return None

    # ------------ Raw memory helpers ------------
    def read_raw(self, address: int, size: int, addr_ext: Optional[int] = None, timeout: Optional[float] = None) -> bytes:
        ae = self.resolve_addr_ext(address) if addr_ext is None else addr_ext
        return self.xcp.read(ae, address, size, timeout=timeout)

    def write_raw(self, address: int, data: bytes, addr_ext: Optional[int] = None, timeout: Optional[float] = None):
        ae = self.resolve_addr_ext(address) if addr_ext is None else addr_ext
        self.xcp.write(ae, address, data, timeout=timeout)

    # ------------ Measurement API ------------
    def read_measurement(self, name: str, addr_ext: Optional[int] = None, timeout: Optional[float] = None) -> Dict[str, Any]:
        """
        Returns:
            {
              "name": str,
              "address": int,
              "addr_ext": int,
              "datatype": str,
              "raw_bytes": bytes,
              "raw_value": int|float,
              "physical_value": float|int,
              "unit": Optional[str]
            }
        """
        m = self.find_measurement(name)
        if not m:
            raise KeyError(f"Measurement '{name}' not found in A2L model")
        if m.ecu_address is None:
            raise ValueError(f"Measurement '{name}' has no address in A2L")

        dt = m.datatype or ""
        size = self._datatype_to_size(dt) or 4
        ae = self.resolve_addr_ext(m.ecu_address) if addr_ext is None else addr_ext
        raw_bytes = self.read_raw(m.ecu_address, size, ae, timeout=timeout)
        raw_value = self._unpack_to_int_or_float(dt, raw_bytes)
        phys = self._apply_compu_to_phys(m.compu_method, raw_value)

        unit = None
        cm = self._compu_by_name.get(m.compu_method or "")
        if cm:
            unit = cm.unit

        return {
            "name": name,
            "address": int(m.ecu_address),
            "addr_ext": ae,
            "datatype": dt,
            "raw_bytes": raw_bytes,
            "raw_value": raw_value,
            "physical_value": phys,
            "unit": unit,
        }

    # ------------ Characteristic API (scalar VALUE) ------------
    def read_characteristic(self, name: str, addr_ext: Optional[int] = None, timeout: Optional[float] = None) -> Dict[str, Any]:
        c = self.find_characteristic(name)
        if not c:
            raise KeyError(f"Characteristic '{name}' not found in A2L")
        if c.address is None:
            raise ValueError(f"Characteristic '{name}' has no address in A2L")
        if (c.char_type or "").upper() not in ("VALUE", "VAL", "SCALAR"):
            raise NotImplementedError(f"Characteristic '{name}' type '{c.char_type}' is not scalar VALUE")

        dtype = self._infer_value_datatype_from_record_layout(c.record_layout) or "UDWORD"
        size = self._datatype_to_size(dtype) or 4
        ae = self.resolve_addr_ext(c.address) if addr_ext is None else addr_ext
        raw_bytes = self.read_raw(c.address, size, ae, timeout)

        if self._is_float_datatype(dtype):
            raw_value = self._unpack_to_int_or_float(dtype, raw_bytes)
        else:
            signed = self._is_signed_datatype(dtype)
            raw_value = int.from_bytes(raw_bytes[:size], self.byteorder, signed=signed)

        phys = self._apply_compu_to_phys(c.compu_method, raw_value)
        cm = self._compu_by_name.get(c.compu_method or "")
        unit = cm.unit if cm and getattr(cm, "unit", None) else getattr(c, "unit", None)

        return {
            "name": name,
            "address": int(c.address),
            "addr_ext": ae,
            "char_type": c.char_type,
            "record_layout": c.record_layout,
            "raw_bytes": raw_bytes,
            "raw_value": raw_value,
            "physical_value": phys,
            "unit": unit,
            "datatype": dtype,
        }

    def write_characteristic(
        self,
        name: str,
        physical_value: float | int,
        addr_ext: Optional[int] = None,
        timeout: Optional[float] = None,
        clamp_limits: bool = True,
    ):
        c = self.find_characteristic(name)
        if not c:
            raise KeyError(f"Characteristic '{name}' not found in A2L")
        if c.address is None:
            raise ValueError(f"Characteristic '{name}' has no address in A2L")
        if (c.char_type or "").upper() not in ("VALUE", "VAL", "SCALAR"):
            raise NotImplementedError(f"Characteristic '{name}' type '{c.char_type}' is not scalar VALUE")

        val_phys = float(physical_value)
        if clamp_limits:
            if c.lower_limit is not None:
                val_phys = max(val_phys, float(c.lower_limit))
            if c.upper_limit is not None:
                val_phys = min(val_phys, float(c.upper_limit))

        raw_val = self._apply_compu_to_raw(c.compu_method, val_phys)

        dtype = self._infer_value_datatype_from_record_layout(c.record_layout) or "UDWORD"
        size = self._datatype_to_size(dtype) or 4
        if self._is_float_datatype(dtype):
            data = self._pack_from_int(dtype, raw_val)
        else:
            signed = self._is_signed_datatype(dtype)
            raw_int = int(round(raw_val))
            raw_int = self._saturate_to_type_range(raw_int, dtype)
            data = int(raw_int).to_bytes(size, self.byteorder, signed=signed)

        ae = self.resolve_addr_ext(c.address) if addr_ext is None else addr_ext
        self.write_raw(c.address, data, ae, timeout)

    # ------------ Convenience using direct values ------------
    def read_measurement_raw_value(self, name: str, addr_ext: Optional[int] = None) -> int | float:
        return self.read_measurement(name, addr_ext)["raw_value"]

    def read_measurement_phys(self, name: str, addr_ext: Optional[int] = None) -> float | int:
        return self.read_measurement(name, addr_ext)["physical_value"]

    def read_characteristic_phys(self, name: str, addr_ext: Optional[int] = None) -> float | int:
        return self.read_characteristic(name, addr_ext)["physical_value"]

    def write_characteristic_phys(self, name: str, phys_value: float | int, addr_ext: Optional[int] = None):
        self.write_characteristic(name, phys_value, addr_ext)