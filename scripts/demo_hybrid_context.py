"""Zero-API demo of hybrid context compression with fallback.

Uses real ContextManager + FakeSemanticSummarizer (no network calls).
Demonstrates:
- Compression before/after message count and tokens
- Semantic summary attempt and structured output
- Failure simulation and deterministic fallback
"""

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROJECT_ROOT))

from src.context_manager import ContextManager, ContextPolicy, estimate_tokens
from src.session import Session


class FakeSemanticSummarizer:
    def __init__(self, fail: bool = False):
        self._fail = fail
        self.call_count = 0

    def summarize(
        self,
        *,
        previous_summary: str,
        messages: list[dict],
        max_output_chars: int,
    ) -> str:
        self.call_count += 1
        if self._fail:
            raise RuntimeError("Simulated semantic summary failure")

        return (
            "Goals:\n"
            "- Test hybrid context compression\n\n"
            "Confirmed Facts:\n"
            "- This is a zero-API demo\n\n"
            "Completed Actions:\n"
            "- Built edge case session\n"
        )


def _make_turn(user_text: str, answer_text: str = "Answer") -> list[dict]:
    return [
        {"role": "user", "content": user_text},
        {"role": "assistant", "content": answer_text},
    ]


def demo_success():
    print("=" * 60)
    print("  DEMO 1: Hybrid compression with successful semantic summary")
    print("=" * 60)

    summarizer = FakeSemanticSummarizer(fail=False)
    policy = ContextPolicy(max_estimated_tokens=1, keep_recent_user_turns=2)
    cm = ContextManager(policy, summarizer=summarizer, summary_mode="hybrid")

    msgs = (
        _make_turn("Hello, how are you?", "I am fine!")
        + _make_turn("What is the capital of France?", "Paris.")
        + _make_turn("Remember the code: 42 is the answer.", "I will remember.")
        + _make_turn("What is my code?", "42 is the answer.")
    )
    session = Session(user_id="demo", session_id="demo-s")
    session.messages = list(msgs)

    tokens_before = estimate_tokens(session.messages)
    msgs_before = len(session.messages)
    print(f"\n  Before compression: {msgs_before} messages, ~{tokens_before} tokens")

    result = cm.prepare_session(session)
    event = cm.last_compression_event

    msgs_after = len(session.messages)
    tokens_after = estimate_tokens(session.messages)
    print(f"  After compression:  {msgs_after} messages, ~{tokens_after} tokens")
    print(f"  Compression triggered: {result}")
    print(f"  Semantic summary attempted: {event['semantic_summary_attempted']}")
    print(f"  Semantic summary succeeded: {event['semantic_summary_succeeded']}")
    print(f"  Fallback used: {event['fallback_used']}")
    print(f"  Summarizer call count: {summarizer.call_count}")
    print(f"\n  Session summary:\n{session.summary[:300]}")
    print(f"\n  Recent messages kept ({len(session.messages)} msgs):")
    for m in session.messages:
        print(f"    [{m['role']}]: {str(m.get('content', ''))[:60]}")


def demo_fallback():
    print("\n" + "=" * 60)
    print("  DEMO 2: Semantic summary failure → deterministic fallback")
    print("=" * 60)

    summarizer = FakeSemanticSummarizer(fail=True)
    policy = ContextPolicy(max_estimated_tokens=1, keep_recent_user_turns=2)
    cm = ContextManager(policy, summarizer=summarizer, summary_mode="hybrid")

    msgs = (
        _make_turn("Hello!", "Hi there!")
        + _make_turn("What is AI?", "Artificial Intelligence.")
        + _make_turn("Tell me a joke.", "Why did the chicken cross the road?")
        + _make_turn("What is Python?", "A programming language.")
    )
    session = Session(user_id="demo", session_id="demo-f")
    session.messages = list(msgs)

    tokens_before = estimate_tokens(session.messages)
    msgs_before = len(session.messages)
    print(f"\n  Before compression: {msgs_before} messages, ~{tokens_before} tokens")

    result = cm.prepare_session(session)
    event = cm.last_compression_event

    msgs_after = len(session.messages)
    tokens_after = estimate_tokens(session.messages)
    print(f"  After compression:  {msgs_after} messages, ~{tokens_after} tokens")
    print(f"  Compression triggered: {result}")
    print(f"  Semantic summary attempted: {event['semantic_summary_attempted']}")
    print(f"  Semantic summary succeeded: {event['semantic_summary_succeeded']}")
    print(f"  Fallback used: {event['fallback_used']}")
    print(f"  Summarizer call count: {summarizer.call_count}")
    print(f"\n  Fallback summary:\n{session.summary[:300]}")
    print(f"\n  Agent can continue — recent messages kept:")
    for m in session.messages:
        print(f"    [{m['role']}]: {str(m.get('content', ''))[:60]}")


def main():
    print("=" * 60)
    print("  Hybrid Context Compression Demo (Zero API)")
    print("  Using FakeSemanticSummarizer — no network calls")
    print("=" * 60)

    demo_success()
    demo_fallback()

    print("\n" + "=" * 60)
    print("  Demo complete.")
    print("  No API calls were made.")
    print("=" * 60)


if __name__ == "__main__":
    main()
