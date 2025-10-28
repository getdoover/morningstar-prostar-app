from pydoover import ui

from .app_config import MorningstarProstarAppConfig

class MorningstarProstarAppUI:
    def __init__(self, config: MorningstarProstarAppConfig):
        self.config = config
        
        self.battery_voltage = ui.NumericVariable(
            "voltage", "Battery Voltage (V)", precision=2, ranges=[
                ui.Range("Low", 0, 10, ui.Colour.red),
                ui.Range("Normal", 10, 20, ui.Colour.green),
                ui.Range("High", 20, 30, ui.Colour.blue),
            ]
        )
        
        self.battery_percent = ui.NumericVariable(
            "batteryPercent", 
            "Battery (%)", 
            precision=1, 
            ranges = [
                ui.Range("Low", 0, 50, ui.Colour.yellow),
                ui.Range("Medium", 50, 75, ui.Colour.blue),
                ui.Range("High", 75, 100, ui.Colour.green)
            ]
        )

        self.remaining_ah = ui.NumericVariable(
            "chargeLevel", 
            "Battery (Ah)", 
            precision=1, 
            ranges = [
                ui.Range("Low", 0, 100, ui.Colour.yellow),
                ui.Range("Medium", 150, 200, ui.Colour.blue),
                ui.Range("High", 200, 230, ui.Colour.green)
            ]
        )

        self.panel_power = ui.NumericVariable(
            "panelPower",
            "Panel Power (W)",
            precision=1,
            ranges = [
                ui.Range("Low", 0, 200, ui.Colour.yellow),
                ui.Range("Medium", 200, 300, ui.Colour.blue),
                ui.Range("High", 300, 480, ui.Colour.green)
            ]
        )

        self.daily_load = ui.NumericVariable(
            "dailyLoad",
            "Daily Load (AHr)",
            precision=1,
        )

        self.daily_charge = ui.NumericVariable(
            "dailyCharge",
            "Panel Charge (AHr)", #CHECK: units
            precision=1,
        )
        
    def fetch(self):
        return (
            self.battery_voltage, 
            self.battery_percent, 
            self.remaining_ah, 
            self.panel_power,
            self.daily_load, 
            self.daily_charge
        )
        
    def update(self, 
        b_voltage=None, 
        b_percent=None, 
        remaining_ah=None, 
        panel_power=None, 
        daily_load=None, 
        daily_charge=None,
        panel_voltage=None,
        panel_current=None,
        load_current=None
    ):
        if b_voltage is not None:
            self.battery_voltage.update(b_voltage)
        if b_percent is not None:
            self.battery_percent.update(b_percent)
        if remaining_ah is not None:
            self.remaining_ah.update(remaining_ah)
        if panel_power is not None:
            self.panel_power.update(panel_power)
        if daily_load is not None:
            self.daily_load.update(daily_load)
        if daily_charge is not None:
            self.daily_charge.update(daily_charge)
        