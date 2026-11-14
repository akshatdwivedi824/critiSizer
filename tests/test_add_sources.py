import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "add_sources", Path(__file__).resolve().parents[1] / "scripts" / "add_sources.py"
)
add_sources = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(add_sources)


def test_parse_list_skips_comments_blanks_and_non_urls():
    text = (
        "# farm laws\n\n"
        "https://thewire.in/a | The Wire headline\n"
        "not a url\n"
        "https://scroll.in/b\n"
    )
    assert add_sources.parse_list(text) == [
        ("https://thewire.in/a", "The Wire headline"),
        ("https://scroll.in/b", None),
    ]


def test_title_from_url_drops_numeric_ids():
    url = "https://theprint.in/india/farm-laws-timeline/768410"
    assert "768410" not in add_sources.title_from_url(url)
    assert add_sources.title_from_url(url) == "Farm laws timeline"