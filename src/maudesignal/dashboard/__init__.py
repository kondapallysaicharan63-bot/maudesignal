"""Streamlit dashboard (F6)."""


def main() -> None:
    """Console entry point.

    Imported lazily so that importing a dashboard submodule (e.g. ``copilot_pages``)
    under Streamlit does not execute ``app`` a second time.
    """
    from maudesignal.dashboard.app import main as _main

    _main()


__all__ = ["main"]
