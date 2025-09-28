from pydoover import ui

from .app_config import MorningstarProstarAppConfig

class MorningstarProstarAppUI:
    def __init__(self, config: MorningstarProstarAppConfig):
        self.config = config
        
        self.battery_voltage = ui.NumericVariable(
            "voltage", "Battery Voltage", precision=2, ranges=[
                ui.Range("Low", 0, 10, ui.Colour.red),
                ui.Range("Normal", 10, 20, ui.Colour.green),
                ui.Range("High", 20, 30, ui.Colour.blue),
            ]
        )
        
        self.battery_1_percent = ui.NumericVariable(
            "batteryPercent", 
            "Battery 1 (%)", 
            precision=1, 
            ranges = [
                ui.Range("Low", 0, 50, ui.Colour.yellow),
                ui.Range("Medium", 50, 75, ui.Colour.blue),
                ui.Range("High", 75, 100, ui.Colour.green)
            ]
        )

        self.remaining_1_ah = ui.NumericVariable(
            "chargeLevel", 
            "Battery 1 (Ah)", 
            precision=1, 
            ranges = [
                ui.Range("Low", 0, 100, ui.Colour.yellow),
                ui.Range("Medium", 150, 200, ui.Colour.blue),
                ui.Range("High", 200, 230, ui.Colour.green)
            ]
        )

        self.battery_1_voltage = ui.NumericVariable(
            "batteryVoltage", 
            "Battery 1 (V)", 
            precision=1, 
            ranges = [
                ui.Range("Low", 0, 23.6, ui.Colour.yellow),
                ui.Range("Medium", 23.6, 24.5, ui.Colour.blue),
                ui.Range("High", 24.5, 26, ui.Colour.green)
            ]
        )

        self.panel_1_power = ui.NumericVariable(
            "panelPower1",
            "Panel 1 Power (W)",
            precision=1,
            ranges = [
                ui.Range("Low", 0, 200, ui.Colour.yellow),
                ui.Range("Medium", 200, 300, ui.Colour.blue),
                ui.Range("High", 300, 480, ui.Colour.green)
            ]
        )

        self.daily_load_1 = ui.NumericVariable(
            "dailyLoad1",
            "Daily Load 1 (AHr)",
            precision=1,
        )

        self.daily_charge_1 = ui.NumericVariable(
            "dailyCharge1",
            "Panel Charge 1 (AHr)", #CHECK: units
            precision=1,
        )
        
    def fetch(self):
        return (
            self.battery_voltage, 
            self.battery_1_percent, 
            self.remaining_1_ah, 
            self.battery_1_voltage, 
            self.panel_1_power,
            self.daily_load_1, 
            self.daily_charge_1
        )
        
    def update(self, b_voltage=None, b_percent=None, remaining_ah=None, panel_power=None, daily_load=None, daily_charge=None):
        if b_voltage is not None:
            self.battery_voltage.update(b_voltage)
        if b_percent is not None:
            self.battery_1_percent.update(b_percent)
        if remaining_ah is not None:
            self.remaining_1_ah.update(remaining_ah)
        if panel_power is not None:
            self.panel_1_power.update(panel_power)
        if daily_load is not None:
            self.daily_load_1.update(daily_load)
        if daily_charge is not None:
            self.daily_charge_1.update(daily_charge)
        