from pathlib import Path

from pydoover import config
from pydoover.docker.modbus import ModbusConfig

from .utils import SystemVoltage


class MorningstarProstarAppConfig(config.Schema):
    # Explicit name= overrides pin the sanitised JSON keys so existing deployed
    # configs keep loading. "System Voltage" / "Modbus Slave ID" already
    # sanitise to these keys unchanged.
    sys_voltage = config.Enum(
        "System Voltage",
        name="system_voltage",
        choices=[
            SystemVoltage.V_12.value,
            SystemVoltage.V_24.value,
            SystemVoltage.V_48.value,
        ],
        default=SystemVoltage.V_24.value,
        description="Nominal system voltage of the battery bank the ProStar charges.",
    )
    # NOTE: the legacy key was "battery_max_(ah)". pydoover 1.9.1's key validator
    # no longer permits parentheses, so this field can only be keyed
    # "battery_max_ah". Deployed instances must have their config key migrated
    # from battery_max_(ah) -> battery_max_ah (see README).
    battery_max_ah = config.Number(
        "Battery Max (Ah)",
        name="battery_max_ah",
        description="Rated amp-hour capacity of the battery bank, used to derive remaining Ah.",
    )
    modbus_slave_id = config.Integer(
        "Modbus Slave ID",
        name="modbus_slave_id",
        description="Modbus slave/unit ID of the ProStar controller on its RS485 bus.",
    )
    # Default display name "Modbus Config" sanitises to the key "modbus_config".
    # For dual-controller (Foamer) skids each app instance MUST set a distinct
    # bus name + serial port, otherwise instances collide in the shared modbus
    # interface's bus registry (see README).
    modbus_config = ModbusConfig()

    @property
    def system_voltage_enum(self) -> SystemVoltage:
        """The configured system voltage as a SystemVoltage member.

        The enum stores raw choices, so the injected value comes back as an int
        (or a str if a deployment stored it that way) rather than a member.
        """
        return SystemVoltage(int(self.sys_voltage.value))

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
    MorningstarProstarAppConfig.export(
        Path(__file__).parents[2] / "doover_config.json", "morningstar_prostar_app"
    )


if __name__ == "__main__":
    export()
