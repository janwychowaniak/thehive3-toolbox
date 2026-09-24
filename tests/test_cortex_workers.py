import unittest

from thehive3_toolbox.cortex import assess_workers


def definition(name, version):
    return {"id": f"{name}_{version}".replace(".", "_"), "name": name, "version": version}


def worker(definition_id, version="0.0"):
    # Cortex reports version "0.0" for a worker whose definition is gone.
    return {"name": definition_id, "workerDefinitionId": definition_id, "version": version,
            "dataTypeList": ["ip"], "configuration": {"key": "must-not-leak"}}


def assess_one(w, definitions):
    (record,) = assess_workers([w], definitions)
    return record


class AssessWorkersTest(unittest.TestCase):

    def test_current_definition_is_ok(self):
        r = assess_one(worker("Lookup_2_0", "2.0"), [definition("Lookup", "2.0")])
        self.assertEqual((r["state"], r["version"], r["available_version"]), ("ok", "2.0", None))

    def test_newer_definition_next_to_the_current_one(self):
        r = assess_one(worker("Lookup_2_0", "2.0"),
                       [definition("Lookup", "2.0"), definition("Lookup", "2.1")])
        self.assertEqual((r["state"], r["available_version"]), ("update_available", "2.1"))

    def test_definition_replaced_by_a_newer_version(self):
        r = assess_one(worker("Lookup_2_0"), [definition("Lookup", "3.0")])
        self.assertEqual((r["state"], r["version"], r["available_version"]),
                         ("definition_missing", "2.0", "3.0"))

    def test_definition_gone_without_successor(self):
        r = assess_one(worker("Retired_1_0"), [definition("Lookup", "3.0")])
        self.assertEqual((r["state"], r["version"], r["available_version"]),
                         ("definition_missing", None, None))

    def test_longest_catalog_name_wins(self):
        r = assess_one(worker("Lookup_Domain_1_0"),
                       [definition("Lookup", "5.0"), definition("Lookup_Domain", "2.0")])
        self.assertEqual((r["version"], r["available_version"]), ("1.0", "2.0"))

    def test_name_prefix_followed_by_a_word_is_not_a_version(self):
        r = assess_one(worker("Lookup_Domain_1_0"), [definition("Lookup", "5.0")])
        self.assertEqual((r["state"], r["available_version"]), ("definition_missing", None))

    def test_versions_compare_numerically(self):
        r = assess_one(worker("Lookup_0_9_1", "0.9.1"),
                       [definition("Lookup", "0.9.1"), definition("Lookup", "0.10.0")])
        self.assertEqual((r["state"], r["available_version"]), ("update_available", "0.10.0"))

    def test_unreadable_catalog_leaves_state_unknown(self):
        r = assess_one(worker("Lookup_2_0", "2.0"), None)
        self.assertEqual((r["state"], r["version"]), (None, "2.0"))

    def test_configuration_never_reaches_the_record(self):
        r = assess_one(worker("Lookup_2_0", "2.0"), [definition("Lookup", "2.0")])
        self.assertNotIn("must-not-leak", repr(r))

    def test_records_sorted_by_name(self):
        records = assess_workers([worker("B_1_0"), worker("A_1_0")], [])
        self.assertEqual([r["name"] for r in records], ["A_1_0", "B_1_0"])


if __name__ == "__main__":
    unittest.main()
