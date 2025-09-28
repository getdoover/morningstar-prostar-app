from pathlib import Path

from pydoover import config
from pydoover.docker.modbus import ModbusConfig
from .utils import SystemVoltage

class MorningstarProstarAppConfig(config.Schema):
    def __init__(self):
        self.sys_voltage = config.Enum("System Voltage", default=SystemVoltage.V_24, description="System voltage for the solar controller")
        self.battery_max_ah = config.Numeric("Battery Max (Ah)", description="Max capacity of the battery")
        self.modbus_slave_id = config.Integer("Modbus Slave ID", description="Modbus Slave ID for Prostar")
        self.modbus_config = ModbusConfig()
        
    @property
    def system_voltage(self):
        return self.sys_voltage.value 
    
    @property
    def battery_capacity(self):
        return self.battery_max_ah.value
    
    @property
    def slave_id(self):
        return self.modbus_slave_id.value

def export():
    MorningstarProstarAppConfig().export(Path(__file__).parents[2] / "doover_config.json", "morningstar_prostar_app")

if __name__ == "__main__":
    export()
