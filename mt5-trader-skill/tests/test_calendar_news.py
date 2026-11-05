"""Calendar parsing, blackout windows, RSS parsing and headline tagging."""

import datetime
import os
import tempfile
import unittest

import _load

econ = _load.load("mt5-calendar", "econ")
news = _load.load("mt5-news", "news")

RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
 <item><title>Dollar jumps as Fed signals a rate cut is off the table</title>
  <description><![CDATA[<p>The greenback rose after Powell spoke.</p>]]></description>
  <link>https://example.com/a</link>
  <pubDate>Fri, 06 Nov 2026 11:30:00 GMT</pubDate></item>
 <item><title>Gold hits a record as safe haven demand soars</title>
  <description>Bullion rallied.</description>
  <link>https://example.com/b</link>
  <pubDate>Fri, 06 Nov 2026 09:00:00 GMT</pubDate></item>
 <item><title>Local football results</title>
  <description>Nothing about markets.</description>
  <link>https://example.com/c</link>
  <pubDate>Fri, 06 Nov 2026 08:00:00 GMT</pubDate></item>
</channel></rss>"""

ATOM = """<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
 <entry><title>ECB holds rates, euro slips</title>
  <summary>Lagarde spoke in Frankfurt.</summary>
  <link href="https://example.com/d"/>
  <updated>2026-11-06T10:00:00Z</updated></entry>
</feed>"""


class TestCalendar(unittest.TestCase):
    def test_parse_times(self):
        iso = econ.parse_time("2026-11-06T13:30:00Z")
        self.assertEqual(iso.hour, 13)
        self.assertEqual(iso.tzinfo, datetime.timezone.utc)
        self.assertEqual(econ.parse_time("2026-11-06 13:30").hour, 13)
        self.assertEqual(econ.parse_time(1793966280).year, 2026)
        self.assertIsNone(econ.parse_time("not a date"))

    def test_normalise_event(self):
        event = econ.normalise_event({"date": "2026-11-06T13:30:00Z", "country": "usd",
                                          "event": "Nonfarm Payrolls", "importance": "3"})
        self.assertEqual(event["currency"], "USD")
        self.assertEqual(event["impact"], "high")
        self.assertEqual(event["title"], "Nonfarm Payrolls")

    def test_bad_event_dropped(self):
        self.assertIsNone(econ.normalise_event({"currency": "USD"}))
        self.assertIsNone(econ.normalise_event("nope"))

    def test_blackout_windows_and_check(self):
        events = [econ.normalise_event({"time": "2026-11-06T13:30:00Z", "currency": "USD",
                                            "title": "NFP", "impact": "high"})]
        windows = econ.blackout_windows(events, 30)
        self.assertEqual(len(windows), 1)
        self.assertEqual(windows[0]["from"][11:16], "13:00")
        self.assertEqual(windows[0]["to"][11:16], "14:00")
        inside = datetime.datetime(2026, 11, 6, 13, 45, tzinfo=datetime.timezone.utc)
        outside = datetime.datetime(2026, 11, 6, 10, 0, tzinfo=datetime.timezone.utc)
        self.assertTrue(econ.inside_blackout(windows, inside, ["USD"]))
        self.assertFalse(econ.inside_blackout(windows, inside, ["JPY"]))
        self.assertFalse(econ.inside_blackout(windows, outside, ["USD"]))

    def test_mt5_calendar_main_offline(self):
        tmp = tempfile.mkdtemp()
        try:
            root = _load.make_trader(tmp)
            path = os.path.join(root, "data", "calendar.json")
            _load.write_json(path, {"events": [
                {"time": "2026-11-06T13:30:00Z", "currency": "USD",
                 "title": "Nonfarm Payrolls", "impact": "high"},
                {"time": "2026-11-06T12:45:00Z", "currency": "EUR",
                 "title": "ECB speech", "impact": "low"}]})
            code = _load.run(econ, ["--trader-dir", root, "--offline", "--write",
                                  "--currencies", "USD,EUR", "--json"])
            self.assertEqual(code, 0)
            data = _load.read_json(os.path.join(root, "calendar.json"))
            self.assertEqual(data["source"], "snapshot")
            self.assertTrue(data["events"])
            self.assertTrue(data["blackouts"])
        finally:
            _load.cleanup(tmp)


class TestNews(unittest.TestCase):
    def test_rss_and_atom_parse(self):
        items = news.parse_feed(RSS, "example")
        self.assertEqual(len(items), 3)
        self.assertIn("Powell", items[0]["summary"])
        self.assertEqual(items[0]["published"], "Fri, 06 Nov 2026 11:30:00 GMT")
        atom = news.parse_feed(ATOM, "example")
        self.assertEqual(len(atom), 1)
        self.assertIn("ECB", atom[0]["title"])

    def test_tagging(self):
        items = news.parse_feed(RSS, "example")
        matched, severity = news.tag_item(items[0], ["USD"], [], [])
        self.assertIn("USD", matched)
        self.assertEqual(severity, "high")     # "rate cut" + "jumps"
        matched, severity = news.tag_item(items[1], ["XAU"], [], [])
        self.assertIn("XAU", matched)
        self.assertEqual(severity, "high")     # "soars"
        matched, _ = news.tag_item(items[2], ["USD"], [], [])
        self.assertEqual(matched, [])

    def test_currency_word_lists_cover_majors(self):
        for cur in ("USD", "EUR", "GBP", "JPY", "CHF", "AUD", "NZD", "CAD"):
            self.assertIn(cur, news.CURRENCY_WORDS)

    def test_offline_snapshot_run(self):
        tmp = tempfile.mkdtemp()
        try:
            root = _load.make_trader(tmp)
            _load.write_json(os.path.join(root, "data", "news.json"), {"items": [
                {"title": "Dollar firms ahead of payrolls", "link": "x",
                 "published": "Fri, 06 Nov 2026 11:30:00 GMT", "source": "test",
                 "summary": "USD strength"},
                {"title": "Weather", "link": "y",
                 "published": "Fri, 06 Nov 2026 11:30:00 GMT", "source": "test",
                 "summary": "sunny"}]})
            code = _load.run(news, ["--trader-dir", root, "--offline", "--json", "--hours", "100000"])
            self.assertEqual(code, 0)
        finally:
            _load.cleanup(tmp)


if __name__ == "__main__":
    unittest.main()
