"""
Basic tests for an application.

This ensures all modules are importable and that the config is valid.
"""

def test_import_app():
    from morningstar_prostar_app.application import MorningstarProstarAppApplication
    assert MorningstarProstarAppApplication

def test_config():
    from morningstar_prostar_app.app_config import MorningstarProstarAppConfig

    config = MorningstarProstarAppConfig()
    assert isinstance(config.to_dict(), dict)

def test_ui():
    from morningstar_prostar_app.app_ui import MorningstarProstarAppUI
    assert MorningstarProstarAppUI

def test_state():
    from morningstar_prostar_app.app_state import MorningstarProstarAppState
    assert MorningstarProstarAppState