from pydoover.tags import Tag, Tags, Delta, AnyChange


class MorningstarProstarAppTags(Tags):
    """Published tag values for the Morningstar ProStar app.

    UI elements bind to these (see ``app_ui.py``) so the dashboard updates
    purely by the main loop setting tags. ``live=True`` republishes the value
    each loop for a watching UI; ``log_on=Delta(...)`` persists a coarse trend
    without logging every 5 s poll.
    """

    # Battery
    b_voltage = Tag("number", default=None, live=True, log_on=Delta(amount=0.1))
    b_percent = Tag("number", default=None, live=True, log_on=Delta(amount=1))
    remaining_ah = Tag("number", default=None, live=True, log_on=Delta(amount=1))

    # Solar panel / array
    panel_voltage = Tag("number", default=None, live=True, log_on=Delta(amount=1))
    panel_current = Tag("number", default=None, live=True, log_on=Delta(amount=0.2))
    panel_power = Tag("number", default=None, live=True, log_on=Delta(amount=5))

    # Load
    load_current = Tag("number", default=None, live=True, log_on=Delta(amount=0.2))

    # Daily energy counters
    daily_load = Tag("number", default=None, live=True, log_on=Delta(amount=0.5))
    daily_charge = Tag("number", default=None, live=True, log_on=Delta(amount=0.5))

    # True while we are successfully polling the controller. Drives the UI
    # no-comms warning (hidden=comms_ok). Defaults True so a freshly started app
    # doesn't flash a warning before its first poll completes.
    comms_ok = Tag("boolean", default=True, live=True, log_on=AnyChange())
