import httpx
import pytest

from critisizer.evidence.gdelt import CollectError, GdeltClient

URL = "https://api.gdeltproject.org/api/v2/doc/doc"
EMPTY = '{"articles": []}'


def response(status=200, text=EMPTY):
    return httpx.Response(status, text=text, request=httpx.Request("GET", URL))


class Scripted:
    """Raises or returns each item in turn."""

    def __init__(self, *items):
        self.items = list(items)
        self.calls = 0

    def get(self, url, params=None):
        self.calls += 1
        item = self.items.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def client(http):
    return GdeltClient(http=http, sleep=lambda s: None, clock=lambda: 100.0)


def test_a_dropped_connection_is_retried():
    http = Scripted(httpx.RemoteProtocolError("server disconnected"), response())
    _, articles = client(http).search("q")
    assert articles == []
    assert http.calls == 2


def test_a_connection_that_keeps_dropping_gives_up_instead_of_crashing():
    drop = httpx.ReadTimeout("timed out")
    http = Scripted(drop, drop, drop)
    with pytest.raises(CollectError, match="gave_up"):
        client(http).search("q")


def test_a_server_error_is_retried_not_raised_raw():
    http = Scripted(response(status=503), response())
    _, articles = client(http).search("q")
    assert articles == []
    assert http.calls == 2