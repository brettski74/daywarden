"""S002.2: the usage report shows household-local buckets, and stays closed without a password."""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from policy import config
from policy.clock import HouseholdClock
from policy.gate import ParentGate, cookie_value
from policy.groups import SiteGroup
from policy.observations import record
from policy.report import parse_form, respond
from policy.store import PolicyStore

SYDNEY = ZoneInfo("Australia/Sydney")
PASSWORD = "secret"
YOUTUBE = "https://www.youtube.com/watch?v=abc"
CLASSROOM = "https://classroom.google.com/u/0/h"

HOUSEHOLD = """
[household]
timezone = "Australia/Sydney"
bucket_length = "5m"

[[clients]]
name = "Younger child"
address = "192.0.2.40"

[[clients]]
name = "Older child"
address = "192.0.2.41"

[[groups]]
name = "School work"
priority = 10
patterns = ["classroom.google.com"]

[[groups.rules]]
condition = "quota_remaining"
when_true = { action = "allow" }
when_false = { action = "deny", message = "Time is up for today." }

[[groups]]
name = "Entertainment"
priority = 30
quota = "2h"
patterns = ["*.youtube.com"]

[[groups.rules]]
condition = "quota_remaining"
when_true = { action = "allow" }
when_false = { action = "deny", message = "Time is up for today." }
"""


def _quiet(_message):
    return None


def _apply(store: PolicyStore, text: str = HOUSEHOLD) -> dict[str, int]:
    config.apply(config.parse(text), store, warn=_quiet, loaded_at=None)
    return {client.name: client.id for client in store.clients()}


def _observe(
    store: PolicyStore,
    moment: datetime,
    url: str = YOUTUBE,
    nbytes: int = 100,
    ip: str = "192.0.2.40",
) -> bool:
    return record(
        store,
        HouseholdClock(SYDNEY),
        {
            "client_ip": ip,
            "url": url,
            "occurred_at": moment.isoformat(),
            "bytes": nbytes,
        },
    )


def _token(page) -> str:
    header = dict(page.headers)["set-cookie"]
    value = header.split(";", 1)[0]
    name, token = value.split("=", 1)
    assert name == "parent_session"
    assert "HttpOnly" in header
    assert "SameSite=Lax" in header
    assert "Path=/usage" in header
    return token


def _signed(store: PolicyStore, now: datetime, client: str, group: str) -> str:
    gate = ParentGate(PASSWORD)
    opened = respond(
        store,
        gate,
        method="POST",
        query={"client": client, "group": group},
        cookie=None,
        form={"password": PASSWORD},
        now=now,
    )
    assert opened.status == 303
    page = respond(
        store,
        gate,
        method="GET",
        query={"client": client, "group": group},
        cookie=_token(opened),
        form={},
        now=now,
    )
    assert page.status == 200
    assert "Enter the parent password." not in page.body
    assert dict(page.headers)["cache-control"] == "no-store"
    return page.body


def _section(body: str, heading: str, following: str) -> str:
    _before, rest = body.split(heading, 1)
    section, _after = rest.split(following, 1)
    return section


def test_observations_show_on_the_household_local_day():
    with PolicyStore(":memory:") as store:
        _apply(store)
        local = datetime(2026, 10, 22, 0, 32, tzinfo=SYDNEY)
        utc = local.astimezone(timezone.utc)
        assert utc.strftime("%H:%M") != "00:32"
        assert _observe(store, utc, nbytes=100)
        assert _observe(store, local + timedelta(minutes=1), nbytes=40)
        body = _signed(store, datetime(2026, 10, 22, 12, tzinfo=SYDNEY), "Younger child", "Entertainment")

        thursday = _section(body, "Thursday 22 October 2026", "Wednesday 21 October 2026")
        assert "00:30 to 00:35" in thursday
        assert thursday.count("00:30 to 00:35") == 1
        assert "140 bytes" in thursday
        assert "<td>5m</td>" in thursday
        assert "Counted time: 5m." in thursday
        assert "Times are Australia/Sydney." in body
        assert utc.strftime("%H:%M") not in body

        wednesday = _section(body, "Wednesday 21 October 2026", "Tuesday 20 October 2026")
        assert "no usage" in wednesday
        assert "00:30" not in wednesday
        assert "140 bytes" not in wednesday


def test_a_day_with_no_traffic_says_no_usage():
    with PolicyStore(":memory:") as store:
        _apply(store)
        now = datetime(2026, 10, 22, 12, tzinfo=SYDNEY)
        gate = ParentGate(PASSWORD)
        opened = respond(
            store, gate, method="POST", query={}, cookie=None, form={"password": PASSWORD}, now=now
        )
        page = respond(
            store,
            gate,
            method="GET",
            query={"client": "Younger child", "group": "Entertainment"},
            cookie=_token(opened),
            form={},
            now=now,
        )
        assert page.status == 200
        assert page.body.count("no usage") == 14
        assert "Counted time" not in page.body
        assert "Traceback" not in page.body
        assert "Internal Server Error" not in page.body


def test_an_open_bucket_is_shown_and_not_counted_yet():
    with PolicyStore(":memory:") as store:
        _apply(store)
        assert _observe(store, datetime(2026, 10, 21, 15, 0, 1, tzinfo=SYDNEY), nbytes=80)
        early = _signed(store, datetime(2026, 10, 21, 15, 4, tzinfo=SYDNEY), "Younger child", "Entertainment")
        wednesday = _section(early, "Wednesday 21 October 2026", "Tuesday 20 October 2026")
        assert "15:00 to 15:05" in wednesday
        assert "not counted yet" in wednesday
        assert "80 bytes" in wednesday
        assert "Counted time: none yet." in wednesday
        assert "no usage" not in wednesday
        assert early.count("no usage") == 13

        later = _signed(store, datetime(2026, 10, 21, 15, 5, tzinfo=SYDNEY), "Younger child", "Entertainment")
        assert "<td>5m</td>" in later
        assert "not counted yet" not in later
        assert "Counted time: 5m." in later


def test_each_bucket_shows_its_clock_time_bytes_and_stored_length():
    with PolicyStore(":memory:") as store:
        ids = _apply(store)
        store.mark_bucket(
            ids["Younger child"],
            "Entertainment",
            datetime(2026, 10, 21, 15, 0),
            length_seconds=150,
            byte_count=140,
        )
        store.mark_bucket(
            ids["Younger child"],
            "Entertainment",
            datetime(2026, 10, 21, 15, 2, 30),
            length_seconds=90,
            byte_count=1000,
        )
        body = _signed(store, datetime(2026, 10, 21, 16, tzinfo=SYDNEY), "Younger child", "Entertainment")
        assert body.index("15:00 to 15:02:30") < body.index("140 bytes")
        assert body.index("140 bytes") < body.index("15:02:30 to 15:04")
        assert body.index("15:02:30 to 15:04") < body.index("1,000 bytes")
        assert "2m 30s" in body
        assert "1m 30s" in body
        assert "Counted time: 4m." in body
        assert "Quota: 2h." in body


def test_a_group_with_no_quota_is_reported():
    with PolicyStore(":memory:") as store:
        _apply(store)
        assert _observe(store, datetime(2026, 10, 21, 9, 2, tzinfo=SYDNEY), CLASSROOM, nbytes=50)
        assert _observe(store, datetime(2026, 10, 21, 15, 2, tzinfo=SYDNEY), nbytes=90)
        now = datetime(2026, 10, 21, 16, tzinfo=SYDNEY)
        school = _signed(store, now, "Younger child", "School work")
        assert "No quota on this group." in school
        assert "09:00 to 09:05" in school
        assert "50 bytes" in school
        assert "15:00" not in school

        video = _signed(store, now, "Younger child", "Entertainment")
        assert "Quota: 2h." in video
        assert "15:00 to 15:05" in video
        assert "90 bytes" in video
        assert "09:00" not in video
        assert "No quota" not in video


def test_another_client_stays_on_their_own_page():
    with PolicyStore(":memory:") as store:
        _apply(store)
        assert _observe(store, datetime(2026, 10, 21, 15, 2, tzinfo=SYDNEY), nbytes=10)
        assert _observe(
            store,
            datetime(2026, 10, 21, 16, 2, tzinfo=SYDNEY),
            nbytes=20,
            ip="192.0.2.41",
        )
        now = datetime(2026, 10, 21, 17, tzinfo=SYDNEY)
        young = _signed(store, now, "Younger child", "Entertainment")
        assert "15:00 to 15:05" in young
        assert "16:00 to 16:05" not in young
        old = _signed(store, now, "Older child", "Entertainment")
        assert "16:00 to 16:05" in old
        assert "15:00 to 15:05" not in old
        assert "20 bytes" in old
        assert "10 bytes" not in old


def test_buckets_older_than_a_fortnight_are_left_out():
    with PolicyStore(":memory:") as store:
        ids = _apply(store)
        store.mark_bucket(
            ids["Younger child"], "Entertainment", datetime(2026, 10, 8, 10, 0), byte_count=5
        )
        store.mark_bucket(
            ids["Younger child"], "Entertainment", datetime(2026, 10, 9, 11, 0), byte_count=6
        )
        body = _signed(store, datetime(2026, 10, 22, 12, tzinfo=SYDNEY), "Younger child", "Entertainment")
        assert "Friday 9 October 2026" in body
        assert "11:00 to 11:05" in body
        assert "Thursday 8 October 2026" not in body
        assert "10:00" not in body


def test_a_bucket_that_reaches_midnight_stays_on_the_day_it_started():
    with PolicyStore(":memory:") as store:
        ids = _apply(store)
        store.mark_bucket(
            ids["Younger child"],
            "Entertainment",
            datetime(2026, 10, 21, 23, 55),
            length_seconds=300,
            byte_count=1,
        )
        store.mark_bucket(
            ids["Younger child"],
            "Entertainment",
            datetime(2026, 10, 21, 23, 50),
            length_seconds=1200,
            byte_count=8,
        )
        body = _signed(store, datetime(2026, 10, 22, 12, tzinfo=SYDNEY), "Younger child", "Entertainment")
        thursday = _section(body, "Thursday 22 October 2026", "Wednesday 21 October 2026")
        assert "no usage" in thursday
        assert "23:55" not in thursday
        assert "23:50" not in thursday
        wednesday = _section(body, "Wednesday 21 October 2026", "Tuesday 20 October 2026")
        assert "23:55 to 24:00" in wednesday
        assert "1 byte" in wednesday
        assert "1 bytes" not in body
        assert "23:50 to 00:10 the next day" in wednesday
        assert "8 bytes" in wednesday
        assert "Counted time: 25m." in wednesday


def test_the_page_asks_for_a_client_and_a_group():
    with PolicyStore(":memory:") as store:
        _apply(store)
        now = datetime(2026, 10, 22, 12, tzinfo=SYDNEY)
        gate = ParentGate(PASSWORD)
        opened = respond(
            store, gate, method="POST", query={}, cookie=None, form={"password": PASSWORD}, now=now
        )
        page = respond(
            store, gate, method="GET", query={}, cookie=_token(opened), form={}, now=now
        )
        assert "Choose a client and a site group." in page.body
        assert "The last 14 days." in page.body
        assert "Times are Australia/Sydney." in page.body
        assert "no usage" not in page.body
        assert page.body.index("School work") < page.body.index("Entertainment")
        assert page.body.index("Younger child") < page.body.index("Older child")


def test_an_unknown_client_or_group_is_not_an_empty_report():
    with PolicyStore(":memory:") as store:
        _apply(store)
        now = datetime(2026, 10, 22, 12, tzinfo=SYDNEY)
        missing_client = _signed(store, now, "No such child", "Entertainment")
        assert "That client is not in the household." in missing_client
        assert "no usage" not in missing_client
        missing_group = _signed(store, now, "Younger child", "No such group")
        assert "That site group is not in the household." in missing_group
        assert "no usage" not in missing_group


def test_names_are_shown_as_text():
    with PolicyStore(":memory:") as store:
        store.save_household(
            "Australia/Sydney",
            [("A<b>", "192.0.2.40", ("192.0.2.40",))],
            (SiteGroup(name="School <work>", priority=10, patterns=("classroom.google.com",)),),
        )
        body = _signed(store, datetime(2026, 10, 22, 12, tzinfo=SYDNEY), "A<b>", "School <work>")
        assert "A<b>" not in body
        assert "School <work>" not in body
        assert body.count("A&lt;b&gt;") >= 2
        assert body.count("School &lt;work&gt;") >= 2
        assert body.count("no usage") == 14


def test_an_unset_timezone_is_named_as_the_machines():
    text = HOUSEHOLD.replace('timezone = "Australia/Sydney"\n', "")
    with PolicyStore(":memory:") as store:
        _apply(store, text)
        body = _signed(store, datetime(2026, 10, 22, 12, tzinfo=SYDNEY), "Younger child", "School work")
        assert "Times are the timezone of this machine." in body
        assert "Australia/Sydney" not in body


def test_without_a_password_the_page_is_closed():
    with PolicyStore(":memory:") as store:
        _apply(store)
        assert _observe(store, datetime(2026, 10, 22, 0, 32, tzinfo=SYDNEY), nbytes=140)
        now = datetime(2026, 10, 22, 12, tzinfo=SYDNEY)
        query = {"client": "Younger child", "group": "Entertainment"}
        for gate in (ParentGate(None), ParentGate("")):
            page = respond(store, gate, method="GET", query=query, cookie=None, form={}, now=now)
            assert page.status == 403
            assert "This page is closed until a parent password is set." in page.body
            assert "Younger child" not in page.body
            assert "00:30" not in page.body
            assert "140" not in page.body
            assert "<option" not in page.body
            assert dict(page.headers)["cache-control"] == "no-store"
            posted = respond(
                store, gate, method="POST", query=query, cookie=None, form={"password": PASSWORD}, now=now
            )
            assert posted.status == 403
            assert "set-cookie" not in dict(posted.headers)
            assert "140" not in posted.body


def test_a_wrong_password_shows_no_usage():
    with PolicyStore(":memory:") as store:
        _apply(store)
        assert _observe(store, datetime(2026, 10, 22, 0, 32, tzinfo=SYDNEY), nbytes=140)
        now = datetime(2026, 10, 22, 12, tzinfo=SYDNEY)
        gate = ParentGate(PASSWORD)
        query = {"client": "Younger child", "group": "Entertainment"}
        page = respond(store, gate, method="GET", query=query, cookie=None, form={}, now=now)
        assert page.status == 200
        assert "Enter the parent password." in page.body
        assert "<option" not in page.body
        assert "Younger child" not in page.body
        assert "00:30" not in page.body
        assert "no usage" not in page.body

        posted = respond(
            store, gate, method="POST", query=query, cookie=None, form={"password": "nope-secret"}, now=now
        )
        assert posted.status == 401
        assert "That password is not right." in posted.body
        assert "nope-secret" not in posted.body
        assert "set-cookie" not in dict(posted.headers)
        assert "00:30" not in posted.body
        assert "140" not in posted.body


def test_the_right_password_opens_the_report_and_a_forged_cookie_does_not():
    with PolicyStore(":memory:") as store:
        _apply(store)
        assert _observe(store, datetime(2026, 10, 22, 0, 32, tzinfo=SYDNEY), nbytes=140)
        now = datetime(2026, 10, 22, 12, tzinfo=SYDNEY)
        gate = ParentGate(PASSWORD)
        posted = respond(
            store,
            gate,
            method="POST",
            query={"client": "Younger child", "group": "Entertainment", "password": PASSWORD},
            cookie=None,
            form={"password": PASSWORD},
            now=now,
        )
        assert posted.status == 303
        location = dict(posted.headers)["location"]
        assert PASSWORD not in location
        parsed = parse_qs(urlparse(location).query)
        assert parsed["client"] == ["Younger child"]
        assert parsed["group"] == ["Entertainment"]
        token = _token(posted)
        page = respond(
            store,
            gate,
            method="GET",
            query={"client": "Younger child", "group": "Entertainment"},
            cookie=token,
            form={},
            now=now,
        )
        assert "00:30 to 00:35" in page.body
        assert "140 bytes" in page.body

        forged = token[:-1] + ("0" if token[-1] != "0" else "1")
        rejected = respond(
            store,
            gate,
            method="GET",
            query={"client": "Younger child", "group": "Entertainment"},
            cookie=forged,
            form={},
            now=now,
        )
        assert "Enter the parent password." in rejected.body
        assert "00:30" not in rejected.body
        assert "140" not in rejected.body

        from_query = respond(
            store,
            gate,
            method="GET",
            query={"password": PASSWORD, "client": "Younger child", "group": "Entertainment"},
            cookie=None,
            form={},
            now=now,
        )
        assert "Enter the parent password." in from_query.body
        assert "00:30" not in from_query.body


def test_a_cookie_header_and_a_form_body_are_read():
    assert cookie_value("a=b; parent_session=abc", "parent_session") == "abc"
    assert cookie_value("parent_session=abc", "parent_session") == "abc"
    assert cookie_value(None, "parent_session") is None
    assert parse_form(b"password=a%2Bb&password=") == {"password": ""}
    assert parse_form(b"password=a%2Bb") == {"password": "a+b"}
