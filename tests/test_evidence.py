import json

import pytest
from sqlalchemy import func, select

from critisizer.evidence.collect import collect_for_policy, enough_to_score
from critisizer.evidence.gdelt import (
    CollectError,
    GdeltClient,
    parse_articles,
)
from critisizer.evidence.query import QUERY_VERSION, build_query, search_phrase
from critisizer.evidence.text import make_excerpt
from critisizer.models import Policy, SourceItem

HT = "https://www.hindustantimes.com/india-news/a-1.html"
TOI = "https://timesofindia.indiatimes.com/city/b/articleshow/2.cms"
HINDU = "https://www.thehindu.com/news/c.ece"
MIRROR = "https://mumbaimirror.indiatimes.com/mumbai/d/articleshow/4.html"


def _row(url, title, seen, domain):
    return {"url": url, "title": title, "seendate": seen, "domain": domain}


GDELT_BODY = json.dumps(
    {
        "articles": [
            _row(HT, "  Waiver for  ex-Agniveers", "20260908T064500Z",
                 "hindustantimes.com"),
            _row(TOI, "20 % posts reserved", "20260823T204500Z",
                 "timesofindia.indiatimes.com"),
            _row(HINDU, "Paywalled piece", "20260820T103000Z", "thehindu.com"),
            _row(MIRROR, "Oppn calls out govt", "20260821T024500Z",
                 "mumbaimirror.indiatimes.com"),
        ]
    }
)

LONG = "The Agnipath scheme was announced in 2022 and changed army recruitment. "
PAGES = {
    HT: "Intro line that is short.\n" + LONG + "More detail follows here.",
    TOI: LONG + "States reserve posts for former recruits under it.",
    HINDU: None,
    MIRROR: LONG,
}


class FakeClient:
    def __init__(self, body=GDELT_BODY):
        self.body = body
        self.queries = []

    def search(self, query):
        self.queries.append(query)
        return self.body, parse_articles(self.body)


def fake_fetch(url):
    return PAGES.get(url)


@pytest.fixture
def policy(session):
    row = Policy(slug="evi-test", name="Agnipath Scheme", year=2022, summary="x")
    session.add(row)
    session.flush()
    return row


def test_query_is_fixed():
    assert QUERY_VERSION == "query_v1"
    query = build_query("Agnipath")
    assert query == build_query("Agnipath")
    assert query.startswith('"Agnipath" sourcelang:english')
    assert "domain:hindustantimes.com" in query


def test_search_phrase_drops_only_trailing_generic_words():
    assert search_phrase("Agnipath Scheme") == "Agnipath"
    assert search_phrase("Electoral Bonds Scheme") == "Electoral Bonds"
    assert search_phrase("Farm Laws") == "Farm Laws"


def test_known_policies_use_their_fixed_phrase():
    assert search_phrase("Farm laws (repealed)", "farm-laws-2020") == "farm laws"
    assert search_phrase("Telecommunications Act", "telecommunications-act-2023") == (
        "Telecommunications Act"
    )
    assert search_phrase("Some New Policy", "new-1") == "Some New"


def test_parse_articles_reads_fields_and_dates():
    articles = parse_articles(GDELT_BODY)
    assert len(articles) == 4
    assert articles[0].title == "Waiver for ex-Agniveers"
    assert articles[0].published_at.year == 2026


def test_parse_articles_empty_and_garbage():
    assert parse_articles("") == []
    with pytest.raises(CollectError):
        parse_articles("Please limit requests to one every 5 seconds")


def test_collect_stores_readable_allowed_items(session, policy):
    report = collect_for_policy(session, policy, FakeClient(), fake_fetch)
    assert report.found == 4
    assert report.stored == 2
    assert report.skipped["not_allowed"] == 1
    assert report.skipped["fetch_failed"] == 1
    items = session.scalars(select(SourceItem)).all()
    assert {i.outlet for i in items} == {"Hindustan Times", "The Times of India"}
    assert all("Agnipath" in i.excerpt for i in items)


def test_collect_keeps_the_run_and_query(session, policy):
    client = FakeClient()
    report = collect_for_policy(session, policy, client, fake_fetch)
    assert client.queries == [build_query("Agnipath")]
    assert report.run_id is not None


def test_page_without_the_phrase_is_skipped(session, policy):
    pages = {HT: "A long paragraph about something else entirely, nothing here."}
    report = collect_for_policy(session, policy, FakeClient(), pages.get)
    assert report.stored == 0
    assert report.skipped["no_mention"] == 1


def test_running_twice_adds_no_duplicates(session, policy):
    collect_for_policy(session, policy, FakeClient(), fake_fetch)
    again = collect_for_policy(session, policy, FakeClient(), fake_fetch)
    assert again.stored == 0
    assert again.skipped["duplicate"] == 2
    count = session.scalar(select(func.count(SourceItem.id)))
    assert count == 2


def test_excerpt_is_capped_and_starts_with_title():
    text = "\n".join(f"Agnipath paragraph number {i} " + "x" * 80 for i in range(40))
    excerpt = make_excerpt("Title", text, "Agnipath", max_chars=300)
    assert excerpt.startswith("Title\n")
    assert len(excerpt) <= len("Title\n") + 300


def test_enough_to_score_needs_three_items_from_two_outlets(session, policy):
    report = collect_for_policy(session, policy, FakeClient(), fake_fetch)
    assert enough_to_score(session, policy.id) is False  # only 2 items
    session.add(
        SourceItem(
            run_id=report.run_id,
            policy_id=policy.id,
            url="https://x/3",
            outlet="The Hindu",
            excerpt="Agnipath third",
            content_hash="h3",
        )
    )
    session.flush()
    assert enough_to_score(session, policy.id) is True


def test_three_items_from_one_outlet_is_not_enough(session, policy):
    report = collect_for_policy(session, policy, FakeClient('{"articles": []}'))
    for n in range(3):
        session.add(
            SourceItem(
                run_id=report.run_id,
                policy_id=policy.id,
                url=f"https://x/{n}",
                outlet="Mint",
                excerpt=f"Agnipath {n}",
                content_hash=f"h{n}",
            )
        )
    session.flush()
    assert enough_to_score(session, policy.id) is False


class _Resp:
    def __init__(self, text, status_code=200):
        self.text = text
        self.status_code = status_code

    def raise_for_status(self):
        return None


class _Http:
    def __init__(self, bodies):
        self.bodies = list(bodies)
        self.calls = 0

    def get(self, url, params=None):
        self.calls += 1
        item = self.bodies.pop(0)
        if item == 429:
            return _Resp("", 429)
        return _Resp(item)


def test_client_retries_after_a_rate_limit_notice():
    sleeps = []
    http = _Http(["Please limit requests to one every 5 seconds", GDELT_BODY])
    client = GdeltClient(http=http, sleep=sleeps.append, clock=lambda: 100.0)
    _, articles = client.search("q")
    assert http.calls == 2
    assert len(articles) == 4
    assert sleeps == [60.0, 6.0]


def test_client_retries_after_http_429():
    http = _Http([429, 429, GDELT_BODY])
    client = GdeltClient(http=http, sleep=lambda s: None, clock=lambda: 100.0)
    _, articles = client.search("q")
    assert http.calls == 3
    assert len(articles) == 4


def test_client_gives_up_after_three_attempts():
    http = _Http([429, 429, 429])
    client = GdeltClient(http=http, sleep=lambda s: None, clock=lambda: 100.0)
    with pytest.raises(CollectError):
        client.search("q")