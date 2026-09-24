import argparse
import contextlib
import io
import unittest

from thehive3_toolbox import hive
from thehive3_toolbox.client import MAX_PAGE

# Operators that resolve through the inverted index (term, terms, range, match).
ALLOWED_OPERATORS = {"_and", "_in", "_field", "_values", "_value", "_lt", "_gt", "_like"}


class StubClient:
    def __init__(self):
        self.searches = []

    def search(self, path, query=None, *, limit, offset=0, sort=None):
        self.searches.append({"path": path, "query": query, "limit": limit, "sort": sort})
        return [], 0


def run(command, *argv):
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    hive.add_arguments(command, parser)
    client = StubClient()
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        getattr(hive, f"cmd_{command}")(client, parser.parse_args(list(argv)))
    return client.searches


def operators(query):
    if isinstance(query, dict):
        for key, value in query.items():
            if key.startswith("_"):
                yield key
            yield from operators(value)
    elif isinstance(query, list):
        for item in query:
            yield from operators(item)


EVERY_CASE_FILTER = ["--status", "Open", "--tag", "a", "--tag", "b", "--owner", "alice",
                     "--older-than", "2y", "--newer-than", "2020-01-31", "--title", "two words",
                     "--limit", "100"]
EVERY_ALERT_FILTER = ["--status", "New", "--tag", "a", "--source", "feed", "--type", "external",
                      "--older-than", "12w", "--newer-than", "30d", "--title", "word"]


class QuerySafetyTest(unittest.TestCase):

    def test_case_filters_use_cheap_operators_only(self):
        (search,) = run("cases", *EVERY_CASE_FILTER)
        self.assertLessEqual(set(operators(search["query"])), ALLOWED_OPERATORS)

    def test_alert_filters_use_cheap_operators_only(self):
        (search,) = run("alerts", *EVERY_ALERT_FILTER)
        self.assertLessEqual(set(operators(search["query"])), ALLOWED_OPERATORS)

    def test_title_words_become_separate_match_clauses(self):
        (search,) = run("cases", "--title", "two  words")
        likes = [c["_like"]["_value"] for c in search["query"]["_and"] if "_like" in c]
        self.assertEqual(likes, ["two", "words"])

    def test_listing_is_one_page_within_bounds_newest_first(self):
        (search,) = run("cases")
        self.assertEqual((search["limit"], search["sort"]), (50, "-createdAt"))

    def test_count_asks_for_one_unsorted_result(self):
        (search,) = run("alerts", "--count")
        self.assertEqual((search["limit"], search["sort"]), (1, None))

    def test_deleted_cases_left_out_by_default(self):
        (search,) = run("cases")
        self.assertIn({"_in": {"_field": "status", "_values": ["Open", "Resolved"]}},
                      search["query"]["_and"])

    def test_limit_above_one_page_is_refused(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            run("cases", "--limit", str(MAX_PAGE + 1))

    def test_unknown_age_format_is_refused(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            run("cases", "--older-than", "3m")


if __name__ == "__main__":
    unittest.main()
