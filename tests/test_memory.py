import tempfile
import unittest
from pathlib import Path

from core.memory import MemoryStore, WorkingMemory


class MemoryStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.path = Path(self.temp_dir.name) / "long_term_memory.json"
        self.store = MemoryStore(self.path)

    def test_memories_persist_and_can_be_forgotten_individually(self):
        emotional = self.store.add("客人珍惜真诚的陪伴", "emotion")
        factual = self.store.add("客人住在苏州", "fact")

        reopened = MemoryStore(self.path)
        self.assertEqual(len(reopened.list_memories()), 2)
        self.assertTrue(reopened.forget(emotional["id"]))
        self.assertEqual([m["id"] for m in reopened.list_memories()], [factual["id"]])

    def test_emotional_memories_are_presented_before_factual_memories(self):
        self.store.add("情感线索：重视被认真倾听", "emotion")
        self.store.add("事实线索：住在苏州", "fact")

        context = self.store.build_context()

        self.assertLess(context.index("情感线索（优先）"), context.index("事实线索"))
        self.assertIn("不得改写薇尔莉特的核心人格", context)

    def test_emotion_gets_the_larger_recall_budget_and_context_is_capped(self):
        emotional_text = "情" * 250
        factual_text = "事" * 250
        self.store.add(emotional_text, "emotion", importance=5)
        self.store.add(factual_text, "fact", importance=5)

        context = self.store.build_context(max_chars=550)

        self.assertIn(emotional_text, context)
        self.assertNotIn(factual_text, context)
        self.assertLessEqual(len(context), 550)

    def test_importance_ranks_memories_within_the_same_region(self):
        self.store.add("较低显著性", "emotion", importance=1)
        self.store.add("更高显著性", "emotion", importance=5)

        context = self.store.build_context()

        self.assertLess(context.index("更高显著性"), context.index("较低显著性"))

    def test_corrupt_memory_file_is_not_overwritten(self):
        self.path.write_text("not valid json", encoding="utf-8")
        store = MemoryStore(self.path)

        with self.assertRaises(RuntimeError):
            store.add("new memory", "fact")

        self.assertEqual(self.path.read_text(encoding="utf-8"), "not valid json")


class WorkingMemoryTests(unittest.TestCase):
    def test_injected_impression_expires_after_requested_replies(self):
        memory = WorkingMemory()
        memory.inject("暂时把这件事当作重要线索", turns=2)

        self.assertIn("短期印象", memory.build_context())
        memory.advance()
        self.assertIn("暂时把这件事", memory.build_context())
        memory.advance()
        self.assertEqual(memory.build_context(), "")

    def test_clear_removes_only_volatile_impressions(self):
        memory = WorkingMemory()
        memory.inject("可能不准确的临时印象")
        memory.clear()

        self.assertEqual(memory.list_impressions(), [])
        self.assertEqual(memory.build_context(), "")

    def test_context_is_bounded_and_keeps_the_newest_impression_first(self):
        memory = WorkingMemory()
        memory.inject("旧" * 45)
        memory.inject("新" * 45)

        context = memory.build_context(max_chars=130)

        self.assertLessEqual(len(context), 130)
        self.assertIn("新" * 45, context)
        self.assertNotIn("旧" * 45, context)


if __name__ == "__main__":
    unittest.main()
