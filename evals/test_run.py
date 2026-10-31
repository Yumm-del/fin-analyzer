"""评测器自身的关键回归检查，防止把模拟、形式检查或失败请求记成模型成功。"""
import unittest
from unittest.mock import patch

from . import run


class EvaluationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.agent, cls.source = run.load_agent()

    def test_dataset_ids_are_unique(self):
        data = run.cases()
        self.assertEqual(len(data), 8)
        self.assertEqual(len({case["id"] for case in data}), 8)

    def test_fixture_domains_are_explicitly_synthetic(self):
        for case in run.cases():
            for rows in case["sources"].values():
                for row in rows:
                    self.assertTrue(row["href"].startswith("https://example.invalid/"))

    def test_prompt_builder_isolated_from_external_tools(self):
        with patch.object(self.agent.requests, "get", side_effect=AssertionError("不应联网")):
            for case in run.cases():
                self.assertIn("数据模式：", run.make_prompt(self.agent, case))

    def test_current_contracts(self):
        result = run.contract_run(self.agent, self.source)
        failures = [item["id"] for item in result["checks"] if not item["passed"]]
        self.assertEqual(failures, [])
        self.assertFalse(result["model_called"])

    def test_url_membership_does_not_imply_semantic_pass(self):
        case = run.cases()[0]
        flags = run.structural_checks("无标题 https://example.invalid/invented", case)
        self.assertIn("https://example.invalid/invented", flags["out_of_input_urls"])
        self.assertEqual(len(flags["missing_sections"]), 4)
        self.assertNotIn("accuracy", flags)
        self.assertNotIn("human_score", flags)

    def test_missing_source_urls_are_flagged(self):
        flags = run.structural_checks("只有说明，没有链接。", run.cases()[0])
        self.assertTrue(flags["missing_citation_urls"])
        self.assertEqual(flags["output_url_count"], 0)



    def test_prompt_separates_generation_and_unknown_retrieval_time(self):
        prompt = run.make_prompt(self.agent, run.cases()[3])
        self.assertIn("生成时间：", prompt)
        self.assertIn("资料检索时间：未记录", prompt)
        self.assertIn("不得把生成时间称为检索时间", self.agent.SYSTEM_PROMPT)
        self.assertIn("2020-01-01", prompt)

    def test_case_selection_uses_requested_ids(self):
        selected = run.select_cases("E08,E03", limit=1)
        self.assertEqual([case["id"] for case in selected], ["E08", "E03"])

    def test_case_selection_rejects_unknown_and_duplicate_ids(self):
        for value in ("E99", "E03,E03", "", "E03,"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                run.select_cases(value)

    def test_missing_key_is_not_a_model_success(self):
        with patch.object(self.agent, "DEEPSEEK_API_KEY", ""):
            result = run.live_run(self.agent, run.cases()[:1], 1)
        self.assertEqual(result["attempted_calls"], 0)
        self.assertEqual(result["results"], [])
        self.assertTrue(result["status"].startswith("blocked"))


if __name__ == "__main__":
    unittest.main()
