import struct
from enum import Enum


def decode_float16(val: int) -> float:
    """Decode a single 16-bit Modbus register as an IEEE-754 half-precision float.

    The ProStar reports most live measurements (voltages, currents, energy
    counters) as half-precision floats packed into one holding register. The
    register comes back as an unsigned 16-bit int; reinterpret those raw bits as
    a half float. ``struct`` has no unsigned-16 packer that pairs with the ``e``
    (half float) format, so map values above 0x7FFF into the signed range first
    and pack with ``h``.
    """
    if val > 32767:
        val -= 65536  # reinterpret as a signed 16-bit integer
    return struct.unpack("e", struct.pack("h", val))[0]


class SystemVoltage(Enum):
    V_12 = 12
    V_24 = 24
    V_48 = 48

    @property
    def full_voltage(self) -> float:
        """Battery terminal voltage taken as ~100% state of charge."""
        return self.value * (25.6 / 24)

    @property
    def empty_voltage(self) -> float:
        """Battery terminal voltage taken as ~0% state of charge."""
        return self.value * (22.0 / 24)

    def get_battery_percentage(self, b_voltage):
        """State of charge (0-100%) from terminal voltage.

        Interpolates linearly between empty_voltage (0%) and full_voltage
        (100%) for the configured system voltage and clamps to [0, 100]. The
        legacy formula divided by full_voltage alone, which reads ~86% on a
        fully discharged 12/24/48 V bank; using the empty voltage anchor makes
        the reading track usable capacity.
        """
        if b_voltage is None:
            return None
        span = self.full_voltage - self.empty_voltage
        percent = (b_voltage - self.empty_voltage) / span * 100
        return round(max(0.0, min(100.0, percent)), 2)


class HoldingRegisters(Enum):
    PANEL_CURRENT = 17
    PANEL_VOLTAGE = 19
    LOAD_CURRENT = 22
    BATTERY_VOLTAGE = 24
    HEAT_SINK_TEMP = 26
    DAILY_LOAD = 68
    DAILY_CHARGE = 67

    @classmethod
    def start_address(cls):
        """Return the minimum register address."""
        return min(item.value for item in cls)

    @classmethod
    def register_count(cls):
        """Return the span of registers (max - min + 1).

        This is the number of registers you need to read in a single block to
        cover every enum value.
        """
        values = [item.value for item in cls]
        return max(values) - min(values) + 1

    @property
    def index(self):
        """Return the index of this register in the Modbus response list."""
        return self.value - self.__class__.start_address()
