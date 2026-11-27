import unittest
from shorts_generator.highlights import _parse_json_loose

class TestFixVerification(unittest.TestCase):
    def test_parse_json_with_think_tags(self):
        raw = "<think>Let me reason about this [0.0s]</think>\n[{\"topic\": \"Frequencies\", \"start_time\": 0.0, \"end_time\": 60.0, \"summary\": \"Discussion on RF.\"}]"
        res = _parse_json_loose(raw)
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0]["topic"], "Frequencies")

    def test_parse_json_with_raw_monologue_brackets(self):
        raw = "We need to output JSON array of topics [moments] according to instructions. [1] moment\n\n[{\"topic\": \"Sinister Medicines\", \"start_time\": 60.0, \"end_time\": 120.0, \"summary\": \"Deep dive into claims.\"}]"
        res = _parse_json_loose(raw)
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0]["topic"], "Sinister Medicines")

    def test_parse_json_codeblock(self):
        raw = "Here is the JSON:\n```json\n[{\"topic\": \"Topic A\", \"start_time\": 10.0, \"end_time\": 25.0, \"summary\": \"Summary A\"}]\n```"
        res = _parse_json_loose(raw)
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0]["topic"], "Topic A")

if __name__ == "__main__":
    unittest.main()
