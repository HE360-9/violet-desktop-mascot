import unittest
from unittest.mock import Mock, patch

import core.llm_api as llm_api


class LLMContextTests(unittest.TestCase):
    def test_memory_is_added_to_user_context_without_changing_persona(self):
        response = Mock()
        response.json.return_value = {
            "choices": [{
                "message": {"content": "收到。"},
                "finish_reason": "stop",
            }]
        }
        history = [
            {"role": "user", "content": "旧问题"},
            {"role": "assistant", "content": "旧回答"},
        ]

        with (
            patch.object(llm_api, "API_KEY", "test-key"),
            patch.object(llm_api, "API_URL", "https://example.invalid/chat"),
            patch.object(llm_api, "MODEL_NAME", "test-model"),
            patch.object(llm_api, "search", return_value="无时效性实时资讯：暂无"),
            patch.object(llm_api.requests, "post", return_value=response) as post,
        ):
            answer, updated_history = llm_api.llm(
                "今天怎么样？",
                "固定人格提示词",
                history,
                memory_context="【长期记忆参考】客人重视陪伴",
            )

        messages = post.call_args.kwargs["json"]["messages"]
        self.assertEqual(answer, "收到。")
        self.assertEqual(messages[0], {"role": "system", "content": "固定人格提示词"})
        self.assertEqual(messages[-1]["role"], "user")
        self.assertIn("【长期记忆参考】", messages[-1]["content"])
        self.assertEqual(len(updated_history), 4)


if __name__ == "__main__":
    unittest.main()
