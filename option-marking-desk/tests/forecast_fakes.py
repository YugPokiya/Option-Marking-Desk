"""Test doubles for Amazon Bedrock's Converse API."""


class FakeBedrock:
    def __init__(self, verdict=None, text=None, exc=None):
        self.verdict, self.text, self.exc, self.calls = verdict, text, exc, []

    def converse(self, **kw):
        self.calls.append(kw)
        if self.exc:
            raise self.exc
        content = []
        if self.text is not None:
            content.append({"text": self.text})
        if self.verdict is not None:
            content.append({"toolUse": {"toolUseId": "t1", "name": "submit_review", "input": self.verdict}})
        return {
            "output": {"message": {"role": "assistant", "content": content}},
            "usage": {"inputTokens": 1234, "outputTokens": 210},
            "stopReason": "tool_use",
        }


PASS = {"status": "pass", "issues": [], "summary": "Inputs consistent; forecast change small.", "confidence": "high"}
