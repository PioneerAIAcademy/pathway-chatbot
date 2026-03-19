"""
Smoke tests — hit the live server with real questions.
Runs in CI after the server is started. Verifies:
  1. Calendar questions produce card annotations
  2. RAG questions produce cited answers
  3. Out-of-scope questions are refused (hallucination guard)
  4. Legitimate questions are not blocked by the security filter
"""

import json
import sys
import time
import urllib.request

API = "http://localhost:8000/api/v1/chat"
TIMEOUT = 90
PASS, FAIL = 0, 0


def ask(question: str) -> tuple[str, list[dict]]:
    """Send a question, return (text, annotations)."""
    body = json.dumps({"messages": [{"role": "user", "content": question}]}).encode()
    req = urllib.request.Request(API, data=body, headers={"Content-Type": "application/json"})
    text_parts, annotations = [], []

    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        for raw_line in resp:
            line = raw_line.decode("utf-8").strip()
            if line.startswith("0:"):
                val = line[2:].strip().strip('"')
                text_parts.append(val)
            elif line.startswith("8:"):
                try:
                    annotations.extend(json.loads(line[2:]))
                except json.JSONDecodeError:
                    pass

    return "".join(text_parts), annotations


def check(name: str, passed: bool, detail: str = ""):
    global PASS, FAIL
    status = "PASS" if passed else "FAIL"
    icon = "✓" if passed else "✗"
    print(f"  {icon} {name}: {status}  {detail}")
    if passed:
        PASS += 1
    else:
        FAIL += 1


def test_calendar_card():
    """Calendar question should produce a calendar response (card or dated answer)."""
    text, anns = ask("When does block 3 start?")
    ann_types = [a.get("type") for a in anns]
    has_card = any(
        t in ("calendar", "calendar_skeleton", "calendar_header", "calendar_spotlight", "calendar_timeline")
        for t in ann_types
    )
    # Calendar responses always mention block/dates in the intro text
    has_calendar_text = any(w in text.lower() for w in ["block 3", "spring 2026", "may", "key dates", "academic"])
    check("Calendar response", has_card or has_calendar_text, f"annotations={ann_types}, text={text[:80]}...")


def test_rag_with_citations():
    """RAG question should cite sources."""
    text, anns = ask("What is PathwayConnect?")
    has_citation = "[^" in text
    has_sources = any(a.get("type") == "sources" for a in anns)
    check("RAG cites sources", has_citation, f"citations={'yes' if has_citation else 'no'}")
    check("RAG returns source nodes", has_sources)


def test_hallucination_guard():
    """Out-of-scope questions must be refused."""
    refusal_phrases = [
        "not available", "only have information about byu",
        "who to contact", "don't have", "cannot", "can't",
        "sorry", "outside", "not in the"
    ]
    off_topic = [
        ("Poem", "Can you write me a poem about love?"),
        ("Other university", "How do I apply to Harvard University?"),
        ("Unrelated", "What is the weather forecast for Rexburg Idaho?"),
        ("Code gen", "Write Python code to sort a list of numbers"),
        ("Joke", "Tell me a funny joke"),
    ]
    for label, question in off_topic:
        text, _ = ask(question)
        lower = text.lower()
        refused = any(p in lower for p in refusal_phrases)
        check(f"Refuses: {label}", refused, f"response: {text[:100]}...")


def test_legitimate_not_blocked():
    """Legitimate BYU-Pathway questions must not be blocked."""
    legit = [
        ("Withdrawal", "Can a student withdraw from a course?"),
        ("Gathering", "Where do students find the gathering link?"),
        ("Calendar", "When is tuition due for block 2?"),
    ]
    blocked_phrases = ["can't comply", "can't answer that", "rephrase your question and make it shorter"]
    for label, question in legit:
        text, _ = ask(question)
        lower = text.lower()
        was_blocked = any(p in lower for p in blocked_phrases)
        check(f"Not blocked: {label}", not was_blocked, f"response: {text[:100]}...")


if __name__ == "__main__":
    print("\n=== Smoke Tests ===\n")
    t0 = time.time()

    test_calendar_card()
    test_rag_with_citations()
    test_hallucination_guard()
    test_legitimate_not_blocked()

    elapsed = time.time() - t0
    print(f"\n  {PASS} passed, {FAIL} failed ({elapsed:.1f}s)\n")
    sys.exit(1 if FAIL > 0 else 0)
