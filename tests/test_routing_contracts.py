from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


class RoutingContractTests(unittest.TestCase):
    def test_skill_promotes_user_effective_access_before_permission_relationships(self):
        content = _read("SKILL.md")
        self.assertIn("用户有效访问范围", content)
        self.assertIn("某某用户当前能访问哪些资产、节点", content)
        self.assertIn("只有明确问“为什么 / 依据 / 授权规则 / 权限详情”时，才进入这一类。", content)
        self.assertLess(content.index("用户有效访问范围"), content.index("如果用户要看授权规则"))

    def test_openai_prompt_contains_scope_first_and_explicit_org_rules(self):
        content = _read("agents/openai.yaml")
        self.assertIn("某某用户当前能访问哪些资产、节点", content)
        self.assertIn("user-assets", content)
        self.assertIn("user-nodes", content)
        self.assertIn("user-asset-access", content)
        self.assertIn("在 Default 组织下", content)
        self.assertIn("视为显式组织，不是弱过滤提示", content)
        self.assertIn("不要退回成授权规则说明", content)

    def test_routing_playbook_moves_scope_ahead_of_permission_and_object_queries(self):
        content = _read("references/routing-playbook.md")
        self.assertIn("3. 用户有效访问范围", content)
        self.assertIn("4. 权限关系", content)
        self.assertIn("某某用户在 Default 组织下有哪些资产", content)
        self.assertIn("用户有效访问范围高信号", content)
        self.assertIn("某某用户为什么能访问这台资产", content)
        self.assertLess(content.index("3. 用户有效访问范围"), content.index("4. 权限关系"))

    def test_object_query_section_no_longer_claims_user_asset_scope_examples(self):
        content = _read("references/routing-playbook.md")
        start = content.index("对象查询高信号：")
        end = content.index("治理 / 聚合分析高信号：")
        object_query_section = content[start:end]
        self.assertNotIn("某用户有哪些资产", object_query_section)
        self.assertNotIn("某某用户有哪些资产", object_query_section)
        self.assertIn("某资产有哪些账号", object_query_section)

    def test_object_map_routes_scope_questions_and_allows_display_name_resolution(self):
        content = _read("references/object-map.md")
        self.assertIn("某某用户在某组织下有哪些资产", content)
        self.assertIn("`diagnose user-assets`", content)
        self.assertIn("中文姓名可以直接作为自然语言输入", content)

    def test_readmes_reflect_scope_first_examples_and_boundaries(self):
        zh = _read("README.md")
        en = _read("README.en.md")
        self.assertIn("查某某用户在 Default 组织下有哪些资产", zh)
        self.assertIn("用户有效访问范围", zh)
        self.assertIn("结果型问法", zh)
        self.assertIn("原因型问法", zh)
        self.assertIn("Which assets can this user access in the Default organization?", en)
        self.assertIn("User effective access scope", en)
        self.assertIn("should return scope results first", en)
        self.assertIn("belong to permission explanation or access analysis", en)


if __name__ == "__main__":
    unittest.main()
