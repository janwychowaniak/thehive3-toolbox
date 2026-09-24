import argparse
import contextlib
import io
import unittest

from thehive3_toolbox import hive
from thehive3_toolbox.client import MAX_RESULTS

# Operators that resolve through the inverted index (term, terms, range, match),
# and _and / _or combining them.
ALLOWED_OPERATORS = {"_and", "_or", "_in", "_field", "_values", "_value", "_lt", "_gt", "_like"}


class StubClient:
    def __init__(self, results=None):
        self.searches = []
        self.results = results or {}  # path -> items returned by a search on it

    def search(self, path, query=None, *, limit, sort=None):
        self.searches.append({"path": path, "query": query, "limit": limit, "sort": sort})
        items = self.results.get(path, [])
        return items, len(items)


def run(command, *argv, results=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    hive.add_arguments(command, parser)
    client = StubClient(results)
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


EVERY_CASE_FILTER = ["--status", "Resolved", "--resolution", "FalsePositive", "--tag", "a",
                     "--tag", "b", "--owner", "alice",
                     "--older-than", "2y", "--newer-than", "2020-01-31", "--title", "two words",
                     "--limit", "10000"]
EVERY_OBSERVABLE_FILTER = ["--value", "192.0.2.1", "--type", "ip", "--ioc", "--tag", "a",
                           "--older-than", "30d", "--newer-than", "2y"]
EVERY_TASK_FILTER = ["--status", "Waiting", "--owner", "alice", "--title", "word",
                     "--older-than", "30d", "--newer-than", "2y"]
EVERY_ALERT_FILTER = ["--status", "New", "--tag", "a", "--source", "feed", "--type", "external",
                      "--older-than", "12w", "--newer-than", "30d", "--title", "word"]


class QuerySafetyTest(unittest.TestCase):

    def test_case_filters_use_cheap_operators_only(self):
        (search,) = run("cases", *EVERY_CASE_FILTER)
        self.assertLessEqual(set(operators(search["query"])), ALLOWED_OPERATORS)

    def test_alert_filters_use_cheap_operators_only(self):
        (search,) = run("alerts", *EVERY_ALERT_FILTER)
        self.assertLessEqual(set(operators(search["query"])), ALLOWED_OPERATORS)

    def test_observable_filters_use_cheap_operators_only(self):
        (search,) = run("observables", *EVERY_OBSERVABLE_FILTER)
        self.assertLessEqual(set(operators(search["query"])), ALLOWED_OPERATORS)

    def test_task_filters_use_cheap_operators_only(self):
        (search,) = run("tasks", *EVERY_TASK_FILTER)
        self.assertLessEqual(set(operators(search["query"])), ALLOWED_OPERATORS)

    def test_open_tasks_by_default(self):
        (search,) = run("tasks")
        self.assertIn({"_in": {"_field": "status", "_values": ["Waiting", "InProgress"]}},
                      search["query"]["_and"])

    def test_cases_of_a_page_fetched_in_one_ids_query(self):
        page = [{"id": "o1", "_parent": "c1"}, {"id": "o2", "_parent": "c2"}, {"id": "o3", "_parent": "c1"}]
        listing, lookup = run("observables", results={"/api/case/artifact/_search": page})
        self.assertEqual((lookup["path"], lookup["query"], lookup["limit"]),
                         ("/api/case/_search", {"_in": {"_field": "_id", "_values": ["c1", "c2"]}}, 2))

    def test_title_words_become_separate_match_clauses(self):
        (search,) = run("cases", "--title", "two  words")
        likes = [c["_like"]["_value"] for c in search["query"]["_and"] if "_like" in c]
        self.assertEqual(likes, ["two", "words"])

    def test_listing_defaults_to_one_plain_search_newest_first(self):
        (search,) = run("cases")
        self.assertEqual((search["limit"], search["sort"]), (100, "-createdAt"))

    def test_resolution_filter(self):
        (search,) = run("cases", "--resolution", "TruePositive", "--resolution", "Other")
        self.assertIn({"_in": {"_field": "resolutionStatus", "_values": ["TruePositive", "Other"]}},
                      search["query"]["_and"])

    def test_count_asks_for_one_unsorted_result(self):
        (search,) = run("alerts", "--count")
        self.assertEqual((search["limit"], search["sort"]), (1, None))

    def test_deleted_cases_left_out_by_default(self):
        (search,) = run("cases")
        self.assertIn({"_in": {"_field": "status", "_values": ["Open", "Resolved"]}},
                      search["query"]["_and"])

    def test_limit_above_the_cap_is_refused(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            run("cases", "--limit", str(MAX_RESULTS + 1))

    def test_unknown_age_format_is_refused(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            run("cases", "--older-than", "3m")


class CaseColumnTest(unittest.TestCase):

    def test_live_deleted_and_missing_cases(self):
        child = {"_parent": "c9"}
        self.assertEqual(hive._case_number({"caseId": 7, "status": "Open"}, child), "#7")
        self.assertEqual(hive._case_number({"caseId": 7, "status": "Deleted"}, child), "#7 (Deleted)")
        self.assertEqual(hive._case_number(None, child), "c9 (missing)")
        self.assertEqual(hive._case_summary(None, child), {"id": "c9", "missing": True})


if __name__ == "__main__":
    unittest.main()
