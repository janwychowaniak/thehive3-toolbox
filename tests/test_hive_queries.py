import argparse
import contextlib
import io
import time
import unittest

from thehive3_toolbox import hive
from thehive3_toolbox.client import MAX_RESULTS

# Operators that resolve through the inverted index (term, terms, range, match),
# and _and / _or combining them.
ALLOWED_OPERATORS = {"_and", "_or", "_in", "_field", "_values", "_value", "_lt", "_gt", "_like"}


class StubClient:
    def __init__(self, results=None, totals=None):
        self.searches = []
        self.results = results or {}  # path -> items returned by a search on it
        self.totals = totals or {}    # path -> total number of hits, if not len(items)

    def search(self, path, query=None, *, limit, sort=None):
        self.searches.append({"path": path, "query": query, "limit": limit, "sort": sort})
        items = self.results.get(path, [])
        return items[:limit], self.totals.get(path, len(items))


def run(command, *argv, results=None, totals=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    hive.add_arguments(command, parser)
    client = StubClient(results, totals)
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
        for search in run("cases", *EVERY_CASE_FILTER):
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

    def test_default_limit_does_not_count_first(self):
        self.assertEqual(len(run("cases")), 1)

    def test_large_limit_on_a_huge_match_set_is_refused_after_counting(self):
        parser = argparse.ArgumentParser()
        parser.add_argument("--json", action="store_true")
        hive.add_arguments("observables", parser)
        client = StubClient(totals={"/api/case/artifact/_search": MAX_RESULTS + 1})
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()), \
                self.assertRaises(hive.ToolboxError):
            hive.cmd_observables(client, parser.parse_args(["--limit", "5000"]))
        (count,) = client.searches  # the count only: the large listing never ran
        self.assertEqual((count["limit"], count["sort"]), (1, None))

    def test_large_limit_on_a_bounded_match_set_is_served(self):
        page = [{"id": f"c{i}"} for i in range(150)]
        count, listing = run("cases", "--limit", "5000", results={"/api/case/_search": page})
        self.assertEqual((count["limit"], count["sort"]), (1, None))
        self.assertEqual((listing["limit"], listing["sort"]), (150, "-createdAt"))

    def test_large_limit_on_a_small_match_set_stays_one_plain_search(self):
        page = [{"id": f"c{i}"} for i in range(40)]
        _, listing = run("cases", "--limit", "5000", results={"/api/case/_search": page})
        self.assertEqual(listing["limit"], 40)

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
        self.assertEqual(hive._case_number({"caseId": 7, "status": "Open"}, "c9"), "#7")
        self.assertEqual(hive._case_number({"caseId": 7, "status": "Deleted"}, "c9"), "#7 (Deleted)")
        self.assertEqual(hive._case_number(None, "c9"), "c9 (missing)")
        self.assertEqual(hive._case_summary(None, "c9"), {"id": "c9", "missing": True})

    def test_no_case_for_results_outside_a_case(self):
        self.assertIsNone(hive._case_number(None, None))
        self.assertIsNone(hive._case_summary(None, None))


class AuditTest(unittest.TestCase):

    EVERY_FILTER = ["--user", "alice", "--operation", "Delete", "--operation", "Update",
                    "--object-type", "case", "--object", "o1", "--older-than", "1d"]

    def test_filters_use_cheap_operators_only(self):
        (search,) = run("audit", *self.EVERY_FILTER)
        self.assertLessEqual(set(operators(search["query"])), ALLOWED_OPERATORS)

    def test_last_seven_days_by_default(self):
        (search,) = run("audit")
        (since,) = [c["_gt"]["createdAt"] for c in search["query"]["_and"] if "_gt" in c]
        self.assertAlmostEqual(since, (time.time() - 7 * 86400) * 1000, delta=60 * 1000)

    def test_whole_history_of_one_object_or_case(self):
        (search,) = run("audit", "--object", "o1")
        self.assertFalse([c for c in search["query"]["_and"] if "_gt" in c])
        lookup, search = run("audit", "--case", "7",
                             results={"/api/case/_search": [{"id": "c7", "caseId": 7}]})
        self.assertEqual(lookup["query"], {"caseId": 7})
        self.assertIn({"rootId": "c7"}, search["query"]["_and"])
        self.assertFalse([c for c in search["query"]["_and"] if "_gt" in c])

    def test_case_only_for_objects_of_a_case(self):
        self.assertEqual(hive._audit_case_id({"objectType": "case_task", "rootId": "c1"}), "c1")
        self.assertIsNone(hive._audit_case_id({"objectType": "alert", "rootId": "a1"}))

    def test_changes_leave_out_empty_values_and_internal_fields(self):
        self.assertEqual(hive._changes({"_id": "x", "metrics": {}, "tags": [], "description": None,
                                        "status": "Resolved"}), "status=Resolved")
        self.assertIsNone(hive._changes({"metrics": {}}))

    def test_changes_are_shown_compactly(self):
        self.assertEqual(hive._changes({"status": "Resolved", "tlp": 2, "summary": "x" * 40}),
                         "status=Resolved, summary=" + "x" * 27 + "..., tlp=2")


if __name__ == "__main__":
    unittest.main()
