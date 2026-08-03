"""Pure-logic unit tests: half-float register decode and battery % calc."""

import struct

import pytest

from morningstar_prostar_app.utils import SystemVoltage, decode_float16


def _encode_half(value: float) -> int:
    """Pack a float as IEEE half precision and return the raw 16-bit register."""
    return struct.unpack("<H", struct.pack("<e", value))[0]


@pytest.mark.parametrize("value", [0.0, 1.5, 12.34, 24.0, 480.0])
def test_decode_float16_roundtrip_positive(value):
    reg = _encode_half(value)
    assert decode_float16(reg) == pytest.approx(value, rel=1e-3, abs=1e-2)


@pytest.mark.parametrize("value", [-2.0, -13.6])
def test_decode_float16_roundtrip_negative(value):
    # Negative half floats have the sign bit set, so the raw register is > 0x7FFF.
    reg = _encode_half(value)
    assert reg > 32767
    assert decode_float16(reg) == pytest.approx(value, rel=1e-3, abs=1e-2)


def test_decode_float16_known_bits():
    # 0x3C00 is IEEE half precision for 1.0.
    assert decode_float16(0x3C00) == pytest.approx(1.0)


def test_battery_percentage_full_and_empty_anchors():
    sv = SystemVoltage.V_24
    # Empty voltage -> 0%, full voltage -> 100%.
    assert sv.get_battery_percentage(sv.empty_voltage) == pytest.approx(0.0)
    assert sv.get_battery_percentage(sv.full_voltage) == pytest.approx(100.0)


def test_battery_percentage_midpoint():
    sv = SystemVoltage.V_24
    midpoint = (sv.empty_voltage + sv.full_voltage) / 2
    assert sv.get_battery_percentage(midpoint) == pytest.approx(50.0, abs=0.1)


def test_battery_percentage_clamped():
    sv = SystemVoltage.V_24
    # Well below empty clamps to 0, well above full clamps to 100.
    assert sv.get_battery_percentage(0) == 0.0
    assert sv.get_battery_percentage(100) == 100.0


def test_battery_percentage_scales_with_system_voltage():
    # A 12 V bank at 24 V terminal voltage would read absurdly high; the anchors
    # are per system voltage so 48 V behaves like 24 V scaled.
    v48 = SystemVoltage.V_48
    assert v48.get_battery_percentage(v48.full_voltage) == pytest.approx(100.0)
    assert v48.get_battery_percentage(v48.empty_voltage) == pytest.approx(0.0)


def test_battery_percentage_none():
    assert SystemVoltage.V_24.get_battery_percentage(None) is None
