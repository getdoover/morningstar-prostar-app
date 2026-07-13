import logging
import time

from pydoover.docker import Application

from .app_config import MorningstarProstarAppConfig
from .app_tags import MorningstarProstarAppTags
from .app_ui import MorningstarProstarAppUI
from .utils import HoldingRegisters, decode_float16

log = logging.getLogger(__name__)

# pydoover's modbus read_registers takes register_type as an int the modbus
# interface maps to a Modbus data model. Per its docstring (and matching the
# other 1.9.x modbus app, iqflow-wind-sensor) 4 == holding registers, read with
# function code 03. The legacy 0.4 app used 3 (input registers / FC04); the
# ProStar aliases both address spaces so that happened to work, but 4 is the
# correct value for the holding registers this map addresses.
MODBUS_HOLDING_REGISTER = 4


class MorningstarProstarAppApplication(Application):
    config_cls = MorningstarProstarAppConfig
    tags_cls = MorningstarProstarAppTags
    ui_cls = MorningstarProstarAppUI

    config: MorningstarProstarAppConfig
    tags: MorningstarProstarAppTags
    ui: MorningstarProstarAppUI

    START_ADDRESS = HoldingRegisters.start_address()  # 17
    NUM_REGISTERS = HoldingRegisters.register_count()  # 52

    async def setup(self):
        self.started = time.time()
        # Poll the controller every 5 s, as the legacy app did.
        self.loop_target_period = 5

    async def main_loop(self):
        registers = await self._read_registers()

        if not self._is_valid_block(registers):
            log.warning(
                "No valid response from ProStar (bus=%s, slave=%s); marking comms not ok",
                self.config.modbus_config.name.value,
                self.config.slave_id,
            )
            await self.tags.comms_ok.set(False)
            return

        values = self._process_state(registers)
        await self._publish(values)
        await self.tags.comms_ok.set(True)

    async def _read_registers(self):
        try:
            return await self.modbus_iface.read_registers(
                bus_id=self.config.modbus_config.name.value,
                modbus_id=self.config.slave_id,
                start_address=self.START_ADDRESS,
                num_registers=self.NUM_REGISTERS,
                register_type=MODBUS_HOLDING_REGISTER,
            )
        except Exception:
            log.exception("Error reading registers from ProStar")
            return None

    def _is_valid_block(self, registers) -> bool:
        # read_registers returns None on failure, or a list of ints on success.
        # Guard the length so decoding never indexes past a short read.
        return isinstance(registers, list) and len(registers) >= self.NUM_REGISTERS

    def _decode(self, registers, reg: HoldingRegisters) -> float:
        return decode_float16(registers[reg.index])

    def _process_state(self, registers) -> dict:
        panel_current = self._decode(registers, HoldingRegisters.PANEL_CURRENT)
        panel_voltage = self._decode(registers, HoldingRegisters.PANEL_VOLTAGE)
        load_current = self._decode(registers, HoldingRegisters.LOAD_CURRENT)
        b_voltage = self._decode(registers, HoldingRegisters.BATTERY_VOLTAGE)
        daily_charge = self._decode(registers, HoldingRegisters.DAILY_CHARGE)
        daily_load = self._decode(registers, HoldingRegisters.DAILY_LOAD)

        b_percent = self.config.system_voltage_enum.get_battery_percentage(b_voltage)
        remaining_ah = self.config.battery_capacity * (b_percent / 100)

        return {
            "b_voltage": round(b_voltage, 2),
            "b_percent": b_percent,
            "remaining_ah": round(remaining_ah, 1),
            "panel_voltage": round(panel_voltage, 2),
            "panel_current": round(panel_current, 2),
            "load_current": round(load_current, 2),
            "panel_power": round(panel_current * panel_voltage, 2),
            "daily_load": round(daily_load, 1),
            "daily_charge": round(daily_charge, 1),
        }

    async def _publish(self, values: dict) -> None:
        await self.tags.b_voltage.set(values["b_voltage"])
        await self.tags.b_percent.set(values["b_percent"])
        await self.tags.remaining_ah.set(values["remaining_ah"])
        await self.tags.panel_voltage.set(values["panel_voltage"])
        await self.tags.panel_current.set(values["panel_current"])
        await self.tags.load_current.set(values["load_current"])
        await self.tags.panel_power.set(values["panel_power"])
        await self.tags.daily_load.set(values["daily_load"])
        await self.tags.daily_charge.set(values["daily_charge"])
