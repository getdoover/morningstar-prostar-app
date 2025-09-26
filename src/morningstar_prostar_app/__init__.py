from pydoover.docker import run_app

from .application import MorningstarProstarAppApplication
from .app_config import MorningstarProstarAppConfig

def main():
    """
    Run the application.
    """
    run_app(MorningstarProstarAppApplication(config=MorningstarProstarAppConfig()))
