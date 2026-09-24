import argparse
import contextlib
import datetime
import io
import time
import unittest

from thehive3_toolbox import hive

from test_hive_queries import ALLOWED_OPERATORS, operators

UTC = datetime.timezone.utc


def ms(*date):
    return int(datetime.datetime(*date, tzinfo=UTC).timestamp() * 1000)


class StubClient:
    def __init__(self, histogram=None):
        self.posts = []
        self.histogram = histogram or {}

    def post(self, path, body, *, params=None):
        self.posts.append((path, body))
        if body["stats"][0]["_agg"] == "time":
            return {str(k): {"createdAt": {"count": n}} for k, n in self.histogram.items()}
        return {}


def run(*argv, client=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    hive.add_arguments("stats", parser)
    client = client or StubClient()
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        hive.cmd_stats(client, parser.parse_args(list(argv)))
    return client.posts


class StatsQueryTest(unittest.TestCase):

    def test_cheap_operators_and_no_scripted_aggregations(self):
        posts = run("--newer-than", "2y", "--older-than", "30d", "--top", "5")
        for _, body in posts:
            self.assertLessEqual(set(operators(body["query"])), ALLOWED_OPERATORS)
            self.assertIn(body["stats"][0]["_agg"], {"field", "time"})
            self.assertEqual(len(body["stats"]), 1)  # _stats flattens several into one object

    def test_default_window_is_the_last_30_days(self):
        before = time.time() * 1000
        _, body = run()[0]
        start = next(c["_gt"]["createdAt"] for c in body["query"]["_and"] if "_gt" in c)
        end = next(c["_lt"]["createdAt"] for c in body["query"]["_and"] if "_lt" in c)
        self.assertEqual(end - start, 30 * 86400 * 1000)
        self.assertAlmostEqual(end, before, delta=60 * 1000)

    def test_window_end_alone_moves_the_30_days_back(self):
        _, body = run("--older-than", "2024-06-30")[0]
        start = next(c["_gt"]["createdAt"] for c in body["query"]["_and"] if "_gt" in c)
        end = next(c["_lt"]["createdAt"] for c in body["query"]["_and"] if "_lt" in c)
        self.assertEqual(end - start, 30 * 86400 * 1000)

    def test_deleted_cases_left_out(self):
        _, body = run()[0]
        self.assertIn({"_in": {"_field": "status", "_values": ["Open", "Resolved"]}},
                      body["query"]["_and"])

    def test_period_follows_window_length(self):
        for window, interval in ((["--newer-than", "20d"], "1d"), (["--newer-than", "12w"], "1w"),
                                 (["--newer-than", "1y"], "1M")):
            intervals = {b["stats"][0]["_interval"] for _, b in run(*window) if b["stats"][0]["_agg"] == "time"}
            self.assertEqual(intervals, {interval}, window)

    def test_empty_window_is_refused(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(hive.ToolboxError):
            run("--newer-than", "10d", "--older-than", "20d")


class PeriodsTest(unittest.TestCase):

    def test_weeks_start_on_monday_utc(self):
        starts = hive._period_starts(ms(2026, 6, 3, 15), ms(2026, 6, 17), "week")
        self.assertEqual(starts, [ms(2026, 6, 1), ms(2026, 6, 8), ms(2026, 6, 15)])

    def test_months_start_on_the_first_and_cross_the_year(self):
        starts = hive._period_starts(ms(2025, 11, 20), ms(2026, 1, 5), "month")
        self.assertEqual(starts, [ms(2025, 11, 1), ms(2025, 12, 1), ms(2026, 1, 1)])

    def test_empty_periods_at_both_ends_are_filled_in(self):
        client = StubClient(histogram={ms(2026, 6, 2): 5})
        start, end = ms(2026, 6, 1, 12), ms(2026, 6, 3, 12)
        periods = hive._histogram(client, "case", {}, "day", start, end)
        self.assertEqual(periods, [{"period": "2026-06-01", "count": 0},
                                   {"period": "2026-06-02", "count": 5},
                                   {"period": "2026-06-03", "count": 0}])

    def test_a_differently_aligned_count_is_never_dropped(self):
        client = StubClient(histogram={ms(2026, 6, 2, 6): 3})
        periods = hive._histogram(client, "case", {}, "day", ms(2026, 6, 1), ms(2026, 6, 3))
        self.assertEqual(sum(p["count"] for p in periods), 3)


if __name__ == "__main__":
    unittest.main()
