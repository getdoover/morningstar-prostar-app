import logging
import time
import struct
import asyncio

from pydoover.docker import Application
from .utils import HoldingRegisters

from .app_config import MorningstarProstarAppConfig
from .app_ui import MorningstarProstarAppUI

log = logging.getLogger()

class MorningstarProstarAppApplication(Application):
    config: MorningstarProstarAppConfig  # not necessary, but helps your IDE provide autocomplete!

    START_REG_NUM = HoldingRegisters.start_address()
    NUM_REGS = HoldingRegisters.register_count()
    REGISTER_TYPE = 3
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        self.started: float = time.time()
        self.ui: MorningstarProstarAppUI = None

    async def setup(self):
        self.ui = MorningstarProstarAppUI(self.config)
        self.ui_manager.add_children(*self.ui.fetch())
        self.loop_target_period = 5

    async def main_loop(self):
        state = await self.modbus_iface.read_registers_async(
            bus_id=self.config.modbus_config.name.value,
            modbus_id=self.config.slave_id,
            start_address=self.START_REG_NUM,
            num_registers=self.NUM_REGS,
            register_type=self.REGISTER_TYPE
        )
        
        if state is not None:
            values=self.process_state(state)
            self.ui.update(**values)
            await self.set_tags(values)
    
    def process_state(self, result):
        panel_current = self._get_val_from_state(result, HoldingRegisters.PANEL_CURRENT)
        panel_voltage = self._get_val_from_state(result, HoldingRegisters.PANEL_VOLTAGE)
        load_current = self._get_val_from_state(result, HoldingRegisters.LOAD_CURRENT)
        b_voltage = self._get_val_from_state(result, HoldingRegisters.BATTERY_VOLTAGE)
        heat_sink_temp = self._get_val_from_state(result, HoldingRegisters.HEAT_SINK_TEMP)
        daily_charge = self._get_val_from_state(result, HoldingRegisters.DAILY_CHARGE)
        daily_load = self._get_val_from_state(result, HoldingRegisters.DAILY_LOAD)
        
        b_percentage = self.config.system_voltage.get_battery_percentage(b_voltage)
        b_ah =  self.config.battery_capacity*b_percentage

        return {
            "b_voltage":b_voltage,
            "b_percent":b_percentage,
            "remaining_ah": b_ah,
            "panel_power": round(panel_current*panel_voltage,2),
            "daily_load":daily_load,
            "heat_sink_temp":heat_sink_temp,
            "daily_charge":daily_charge
        }
        
        
        
    def _get_val_from_state(self, state, reg_enum: HoldingRegisters):
        val = state[reg_enum.index]
        return self.int_to_float16_bits(val)
        
    def int_to_float16_bits(self, val: int) -> float:
        if val > 32767:
            val -= 65536  # Convert to signed 16-bit integer
        return struct.unpack('e', struct.pack('h', val))[0]  # Pack as unsigned short
