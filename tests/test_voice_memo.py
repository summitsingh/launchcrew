"""Voice memo coverage: transcript validation and section shape.

Pure stdlib unittest with synthetic fixtures only. No DB, no network.
"""

import unittest

from launchcrew import voice_memo as vm


class NormalizeTests(unittest.TestCase):
    def test_version_and_provenance(self):
        self.assertEqual(vm.MODULE_VERSION, "voice-memo/v1")
        self.assertEqual(vm.PROVENANCE, "voice_transcript")

    def test_ok_collapses_whitespace(self):
        self.assertEqual(vm.normalize_transcript("  hello   world\n"), "hello world")

    def test_bad_inputs_raise(self):
        for bad in ("", "   ", None, 42, "x" * 5001, ["hello"]):
            with self.subTest(bad=repr(bad)[:20]):
                with self.assertRaises(ValueError):
                    vm.normalize_transcript(bad)


class SectionTests(unittest.TestCase):
    def test_section_shape(self):
        section = vm.build_memo_section("vm_1", "Launch the wallet", 3, "owner")
        self.assertEqual(section["id"], "vm_1")
        self.assertEqual(section["transcript"], "Launch the wallet")
        self.assertEqual(section["media_provenance"], "voice_transcript")
        self.assertEqual(section["revision"], 3)
        self.assertEqual(section["actor"], "owner")

    def test_section_rejects_bad_transcript(self):
        with self.assertRaises(ValueError):
            vm.build_memo_section("vm_1", "  ", 1, "owner")


if __name__ == "__main__":
    unittest.main()
