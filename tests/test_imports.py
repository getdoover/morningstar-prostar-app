"""
Basic tests for an application.

This ensures all modules are importable and that the config is valid.
"""


def test_import_app():
    from morningstar_prostar_app.application import MorningstarProstarAppApplication

    assert MorningstarProstarAppApplication
    assert MorningstarProstarAppApplication.config_cls is not None
    assert MorningstarProstarAppApplication.tags_cls is not None
    assert MorningstarProstarAppApplication.ui_cls is not None


def test_config():
    from morningstar_prostar_app.app_config import MorningstarProstarAppConfig

    schema = MorningstarProstarAppConfig.to_schema()
    assert isinstance(schema, dict)
    assert len(schema["properties"]) > 0


def test_tags():
    from morningstar_prostar_app.app_tags import MorningstarProstarAppTags

    assert MorningstarProstarAppTags


def test_ui():
    from morningstar_prostar_app.app_ui import MorningstarProstarAppUI
    from pydoover.ui import UI

    assert issubclass(MorningstarProstarAppUI, UI)
