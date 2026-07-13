from pathlib import Path

from pydoover import ui

from .app_tags import MorningstarProstarAppTags as Tags


class MorningstarProstarAppUI(ui.UI):
    # Battery voltage and Ah ranges are derived from config in setup() (they
    # depend on the configured system voltage and battery capacity). Battery %
    # is intrinsically 0-100 so its bands are static.
    battery_voltage = ui.NumericVariable(
        "Battery Voltage",
        name="voltage",
        value=Tags.b_voltage,
        units="V",
        precision=2,
    )
    battery_percent = ui.NumericVariable(
        "Battery",
        name="batteryPercent",
        value=Tags.b_percent,
        units="%",
        precision=1,
        ranges=[
            ui.Range("Low", 0, 50, colour=ui.Colour.yellow),
            ui.Range("Medium", 50, 75, colour=ui.Colour.blue),
            ui.Range("High", 75, 100, colour=ui.Colour.green),
        ],
    )
    remaining_ah = ui.NumericVariable(
        "Battery Charge",
        name="chargeLevel",
        value=Tags.remaining_ah,
        units="Ah",
        precision=1,
    )
    panel_power = ui.NumericVariable(
        "Panel Power",
        name="panelPower",
        value=Tags.panel_power,
        units="W",
        precision=1,
    )
    daily_load = ui.NumericVariable(
        "Daily Load",
        name="dailyLoad",
        value=Tags.daily_load,
        units="Ah",
        precision=1,
    )
    daily_charge = ui.NumericVariable(
        "Panel Charge",
        name="dailyCharge",
        value=Tags.daily_charge,
        units="Ah",
        precision=1,
    )

    comms_warning = ui.WarningIndicator(
        "No communication with solar controller",
        name="commsWarning",
        hidden=Tags.comms_ok,
    )

    details = ui.Submodule(
        "Details",
        name="details",
        children=[
            ui.NumericVariable(
                "Panel Voltage",
                name="panelVoltage",
                value=Tags.panel_voltage,
                units="V",
                precision=2,
            ),
            ui.NumericVariable(
                "Panel Current",
                name="panelCurrent",
                value=Tags.panel_current,
                units="A",
                precision=2,
            ),
            ui.NumericVariable(
                "Load Current",
                name="loadCurrent",
                value=Tags.load_current,
                units="A",
                precision=2,
            ),
        ],
    )

    async def setup(self):
        sv = self.config.system_voltage_enum
        empty = sv.empty_voltage
        full = sv.full_voltage
        self.battery_voltage.ranges = [
            ui.Range("Low", 0, round(empty, 2), colour=ui.Colour.red),
            ui.Range("Normal", round(empty, 2), round(full, 2), colour=ui.Colour.green),
            ui.Range("High", round(full, 2), round(full * 1.15, 2), colour=ui.Colour.blue),
        ]

        capacity = self.config.battery_capacity
        if capacity:
            self.remaining_ah.ranges = [
                ui.Range("Low", 0, round(capacity * 0.5, 1), colour=ui.Colour.yellow),
                ui.Range("Medium", round(capacity * 0.5, 1), round(capacity * 0.8, 1), colour=ui.Colour.blue),
                ui.Range("High", round(capacity * 0.8, 1), round(capacity, 1), colour=ui.Colour.green),
            ]


def export():
    MorningstarProstarAppUI(None, None, None).export(
        Path(__file__).parents[2] / "doover_config.json", "morningstar_prostar_app"
    )


if __name__ == "__main__":
    export()
