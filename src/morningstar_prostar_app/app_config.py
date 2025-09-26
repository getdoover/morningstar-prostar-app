from pathlib import Path

from pydoover import config


class MorningstarProstarAppConfig(config.Schema):
    def __init__(self):
        self.outputs_enabled = config.Boolean("Digital Outputs Enabled", default=True)
        self.funny_message = config.String("A Funny Message")  # this will be required as no default given.

        self.sim_app_key = config.Application("Simulator App Key", description="The app key for the simulator")


def export():
    MorningstarProstarAppConfig().export(Path(__file__).parents[2] / "doover_config.json", "morningstar_prostar_app")

if __name__ == "__main__":
    export()
