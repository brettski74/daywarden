"""Which decision documents the addon will enforce."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "proxy"))

import decision


def test_the_three_decisions_are_recognized():
    allow = {"action": "allow"}
    deny = {"action": "deny", "status": 403, "message": "Time is up for today."}
    redirect = {
        "action": "redirect",
        "status": 302,
        "location": "http://192.168.1.10:8080/tasks/next",
    }
    assert decision.recognize(allow) == allow
    assert decision.recognize(deny) == deny
    assert decision.recognize(redirect) == redirect
    assert decision.recognize(
        {"action": "redirect", "status": 302, "location": "https://tasks.example/next"}
    )["location"].startswith("https://")


def test_other_documents_are_not_decisions():
    rejected = [
        None,
        [],
        "allow",
        {"action": "nope"},
        {"action": "allow", "message": "extra"},
        {"action": "deny", "status": 401, "message": "no"},
        {"action": "deny", "status": 403},
        {"action": "deny", "status": 403, "message": 5},
        {"action": "redirect", "status": 301, "location": "http://tasks.example/next"},
        {"action": "redirect", "status": 302, "location": "/tasks/next"},
        {"action": "redirect", "status": 302, "location": "http://tasks.example/next\r\nX: y"},
        {"action": "redirect", "status": 302, "location": "javascript:alert(1)"},
    ]
    assert [decision.recognize(item) for item in rejected] == [None] * len(rejected)
