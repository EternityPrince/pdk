import unittest

from pydantic import ValidationError

from pmpt.models import PromptDraft, TagSet


class ModelsTest(unittest.TestCase):
    def test_tag_set_normalizes_deduplicates_and_splits_csv(self):
        tags = TagSet.from_values([" Study,school ", "study", "Math"])
        self.assertEqual(tags.names, ("study", "school", "math"))

    def test_prompt_draft_rejects_blank_names(self):
        with self.assertRaises(ValidationError):
            PromptDraft(name=" ", body="body")


if __name__ == "__main__":
    unittest.main()
