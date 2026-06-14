from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = SKILL_ROOT / "scripts" / "library.py"
SPEC = importlib.util.spec_from_file_location("expression_spark_library", SCRIPT)
assert SPEC and SPEC.loader
library = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(library)


class LibraryCliTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "library"
        result = self.run_cli(
            "init",
            "--user-slug",
            "test-user",
            "--name",
            "测试用户",
            "--business",
            "内容咨询",
            "--domains",
            "短视频,客户服务",
            "--default-mode",
            "deep-interviewer",
            "--backend",
            "filesystem",
            "--root",
            str(self.root),
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def run_cli(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPT), *args],
            capture_output=True,
            text=True,
            check=False,
        )

    def write_payload(self, payload: dict, name: str = "payload.json") -> Path:
        path = Path(self.temp.name) / name
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return path

    def payload(
        self,
        session_number: int,
        quote_count: int = 4,
        signal_status: str = "tentative",
        include_core_signals: bool = False,
    ) -> dict:
        session_id = f"2026-06-{session_number:02d}-session"
        themes = ["业务判断", "客户选择", "个人成长"]
        quotes = [
            {
                "id": f"q-{session_number:02d}-{index:02d}",
                "text": f"第{session_number}次会话的原话{index}，不是所有给钱多的客户都值得接。",
                "theme": themes[(session_number + index) % len(themes)],
                "story_or_decision": index == 1,
            }
            for index in range(1, quote_count + 1)
        ]
        topics = [
            {
                "id": f"topic-{session_number:02d}",
                "title": f"第{session_number}个选题",
                "fact_core": "用户做了一个具体决定。",
                "tension": "短期收入与长期交付质量。",
                "audience": "服务型创业者",
                "angles": ["什么客户不该接"],
                "theme": themes[session_number % len(themes)],
                "quote_ids": [quotes[0]["id"]],
            }
        ]
        signals = []
        if include_core_signals:
            for index in range(1, 4):
                signals.append(
                    {
                        "id": f"voice-{index}",
                        "type": "voice",
                        "claim": f"表达模式 {index}",
                        "status": signal_status,
                        "confidence": 0.7,
                        "evidence_quote_ids": [quotes[(index - 1) % len(quotes)]["id"]],
                    }
                )
            signals.extend(
                [
                    {
                        "id": f"value-{session_number}",
                        "type": "value",
                        "claim": f"用户确认的价值观 {session_number}",
                        "status": "confirmed",
                        "user_confirmed": True,
                        "confidence": 0.9,
                        "evidence_quote_ids": [quotes[0]["id"]],
                    }
                ]
            )
        return {
            "confirmed": True,
            "session": {
                "id": session_id,
                "date": f"2026-06-{session_number:02d}",
                "mode": "deep-interviewer",
                "summary": "只保存经确认的精选表达。",
                "themes": [themes[session_number % len(themes)]],
            },
            "quotes": quotes,
            "topics": topics,
            "signals": signals,
            "next_threads": ["这个决定后来带来了什么变化？"],
        }

    def register(self, payload: dict, name: str) -> subprocess.CompletedProcess[str]:
        path = self.write_payload(payload, name)
        return self.run_cli("register", "--library", str(self.root), "--payload", str(path))

    def state(self) -> dict:
        return json.loads((self.root / "state.json").read_text(encoding="utf-8"))

    def test_init_creates_expected_structure_without_corpus_in_state(self) -> None:
        for directory in library.REQUIRED_DIRS:
            self.assertTrue((self.root / directory).is_dir())
        state_text = (self.root / "state.json").read_text(encoding="utf-8")
        for forbidden in ('"text"', '"claim"', '"summary"', '"fact_core"'):
            self.assertNotIn(forbidden, state_text)
        self.assertIn("不保存完整聊天记录", (self.root / "config.md").read_text(encoding="utf-8"))

    def test_register_rejects_unconfirmed_payload(self) -> None:
        payload = self.payload(1)
        payload["confirmed"] = False
        result = self.register(payload, "unconfirmed.json")
        self.assertEqual(result.returncode, 2)
        self.assertIn("confirmed: true", result.stderr)
        self.assertEqual(self.state()["stats"]["sessions"], 0)

    def test_register_preserves_exact_quotes_and_validates(self) -> None:
        payload = self.payload(1)
        exact = "这句话，我不想让 AI 帮我润色。"
        payload["quotes"][0]["text"] = exact
        result = self.register(payload, "confirmed.json")
        self.assertEqual(result.returncode, 0, result.stderr)
        session_file = next((self.root / "sessions").rglob("*.md"))
        self.assertIn(exact, session_file.read_text(encoding="utf-8"))
        self.assertNotIn(exact, (self.root / "state.json").read_text(encoding="utf-8"))
        validation = self.run_cli("validate", "--library", str(self.root), "--json")
        self.assertEqual(validation.returncode, 0, validation.stdout + validation.stderr)
        self.assertTrue(json.loads(validation.stdout)["ok"])

    def test_register_rejects_full_transcript_in_summary(self) -> None:
        payload = self.payload(1)
        payload["session"]["summary"] = "长" * 601
        result = self.register(payload, "full-transcript.json")
        self.assertEqual(result.returncode, 2)
        self.assertIn("not a full transcript", result.stderr)
        self.assertEqual(self.state()["stats"]["sessions"], 0)

    def test_default_mode_updates_only_when_explicit(self) -> None:
        first = self.payload(1)
        first["session"]["mode"] = "gentle-journal"
        result = self.register(first, "session-mode-only.json")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.state()["settings"]["default_mode"], "deep-interviewer")
        second = self.payload(2)
        second["session"]["mode"] = "content-coach"
        second["update_default_mode"] = True
        result = self.register(second, "default-mode.json")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.state()["settings"]["default_mode"], "content-coach")
        self.assertIn('default_mode: "content-coach"', (self.root / "config.md").read_text(encoding="utf-8"))

    def test_confirmed_signal_cannot_be_silently_rewritten(self) -> None:
        first = self.payload(1)
        first["signals"] = [
            {
                "id": "confirmed-value",
                "type": "value",
                "claim": "用户明确看重长期信任。",
                "status": "confirmed",
                "user_confirmed": True,
                "evidence_quote_ids": [first["quotes"][0]["id"]],
            }
        ]
        self.assertEqual(self.register(first, "confirmed-value.json").returncode, 0)
        second = self.payload(2)
        second["signals"] = [
            {
                "id": "confirmed-value",
                "type": "value",
                "claim": "用户只看重短期收益。",
                "status": "tentative",
                "evidence_quote_ids": [second["quotes"][0]["id"]],
            }
        ]
        result = self.register(second, "silent-rewrite.json")
        self.assertEqual(result.returncode, 2)
        self.assertIn("cannot change claim", result.stderr)
        self.assertEqual(self.state()["stats"]["sessions"], 1)

    def test_persona_generation_requires_existing_generated_file(self) -> None:
        missing = {
            "confirmed": True,
            "persona_generation": {
                "user_confirmed": True,
                "path": "generated/test-user-persona/SKILL.md",
            },
        }
        result = self.register(missing, "missing-persona.json")
        self.assertEqual(result.returncode, 2)
        self.assertIn("must exist", result.stderr)
        persona_path = self.root / "generated" / "test-user-persona" / "SKILL.md"
        persona_path.parent.mkdir(parents=True)
        persona_path.write_text("---\nname: test-user-persona\ndescription: test\n---\n", encoding="utf-8")
        result = self.register(missing, "existing-persona.json")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.state()["persona"]["path"], "generated/test-user-persona/SKILL.md")

    def test_recurring_signal_requires_three_sessions(self) -> None:
        first = self.payload(1, include_core_signals=True)
        first["signals"] = first["signals"][:3]
        self.assertEqual(self.register(first, "first.json").returncode, 0)
        second = self.payload(2, include_core_signals=True)
        second["signals"] = second["signals"][:3]
        for signal in second["signals"]:
            signal["status"] = "recurring"
        result = self.register(second, "second.json")
        self.assertEqual(result.returncode, 2)
        self.assertIn("cannot be recurring", result.stderr)

    def test_readiness_thresholds_and_context(self) -> None:
        for session_number in range(1, 7):
            status = "recurring" if session_number >= 3 else "tentative"
            payload = self.payload(
                session_number,
                quote_count=5,
                signal_status=status,
                include_core_signals=True,
            )
            result = self.register(payload, f"session-{session_number}.json")
            self.assertEqual(result.returncode, 0, result.stderr)
        stats = self.state()["stats"]
        self.assertTrue(stats["voice_preview"]["ready"])
        self.assertTrue(stats["stable_persona"]["ready"])
        self.assertEqual(stats["recurring_voice_patterns"], 3)
        self.assertGreaterEqual(stats["confirmed_values_or_stances"], 3)
        context = self.run_cli(
            "context",
            "--library",
            str(self.root),
            "--query",
            "客户",
            "--limit",
            "3",
        )
        self.assertEqual(context.returncode, 0, context.stderr)
        self.assertIn("Source sessions with exact quotes", context.stdout)
        self.assertIn("不是所有给钱多的客户都值得接", context.stdout)

    def test_feedback_export_separates_metadata_from_confirmed_content(self) -> None:
        payload = self.payload(1)
        payload["quotes"][0]["text"] = "这是一条确认原话，api_key=should-not-leak-123456。"
        self.assertEqual(self.register(payload, "feedback-source.json").returncode, 0)
        metadata = self.run_cli("feedback", "--library", str(self.root))
        self.assertEqual(metadata.returncode, 0, metadata.stderr)
        self.assertIn("仅统计与索引", metadata.stdout)
        self.assertIn("短小、多段会话是允许的真实表达形态", metadata.stdout)
        self.assertNotIn("这是一条确认原话", metadata.stdout)
        content = self.run_cli(
            "feedback",
            "--library",
            str(self.root),
            "--include-content",
            "--session-limit",
            "1",
        )
        self.assertEqual(content.returncode, 0, content.stderr)
        self.assertIn("这是一条确认原话", content.stdout)
        self.assertNotIn("should-not-leak-123456", content.stdout)
        self.assertIn("api_key=[REDACTED]", content.stdout)

    def test_forget_requires_preview_then_rebuilds(self) -> None:
        payload = self.payload(1, include_core_signals=True)
        result = self.register(payload, "forget-source.json")
        self.assertEqual(result.returncode, 0, result.stderr)
        before = self.state()["stats"]["quotes"]
        dry_run = self.run_cli(
            "forget",
            "--library",
            str(self.root),
            "--contains",
            "给钱多的客户",
            "--dry-run",
        )
        self.assertEqual(dry_run.returncode, 0, dry_run.stderr)
        self.assertEqual(self.state()["stats"]["quotes"], before)
        impact = json.loads(dry_run.stdout)["impact"]
        self.assertGreater(len(impact["quotes_to_delete"]), 0)
        apply = self.run_cli(
            "forget",
            "--library",
            str(self.root),
            "--contains",
            "给钱多的客户",
            "--apply",
        )
        self.assertEqual(apply.returncode, 0, apply.stdout + apply.stderr)
        self.assertEqual(self.state()["stats"]["quotes"], 0)
        self.assertTrue(json.loads(apply.stdout)["validation"]["ok"])

    def test_forgetting_signal_preserves_contradiction_integrity(self) -> None:
        payload = self.payload(1)
        payload["signals"] = [
            {
                "id": "old-stance",
                "type": "stance",
                "claim": "用户过去更看重效率。",
                "status": "confirmed",
                "user_confirmed": True,
                "evidence_quote_ids": [payload["quotes"][0]["id"]],
            },
            {
                "id": "new-tension",
                "type": "tension",
                "claim": "用户有时愿意为了团队关系牺牲效率。",
                "status": "contradicted",
                "contradicts": ["old-stance"],
                "evidence_quote_ids": [payload["quotes"][1]["id"]],
            },
        ]
        result = self.register(payload, "contradiction.json")
        self.assertEqual(result.returncode, 0, result.stderr)
        apply = self.run_cli(
            "forget",
            "--library",
            str(self.root),
            "--signal-id",
            "old-stance",
            "--apply",
        )
        self.assertEqual(apply.returncode, 0, apply.stdout + apply.stderr)
        signal = self.state()["records"]["signals"]["new-tension"]
        self.assertEqual(signal["status"], "tentative")
        self.assertEqual(signal["contradicts"], [])


if __name__ == "__main__":
    unittest.main()
