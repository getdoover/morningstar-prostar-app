from pydoover.docker import run_app

from .application import MorningstarProstarAppApplication


def main():
    """Run the application."""
    run_app(MorningstarProstarAppApplication())
