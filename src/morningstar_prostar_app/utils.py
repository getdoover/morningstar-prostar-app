from enum import Enum

class SystemVoltage(Enum):
    V_12 = 12
    V_24 = 24
    V_48 = 48
    
    @property
    def full_voltage(self):
        return self.value * (25.6 / 24)
    @property
    def empty_voltage(self):
        return self.value * (22.0 / 24)
    
    def get_battery_percentage(self, b_voltage):
        return round((b_voltage/self.full_voltage)*100,2)

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
        """
        Return the span of registers (max - min).
        This gives the number of registers you’d need to read in a block
        to cover all enum values.
        """
        values = [item.value for item in cls]
        return max(values) - min(values)
    
    @property
    def index(self):
        """Return the index of this register in the Modbus response list."""
        return self.value - self.__class__.start_address()-1