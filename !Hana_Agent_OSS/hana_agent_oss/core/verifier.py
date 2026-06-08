from __future__ import annotations

from hana_agent_oss.core.protocol import ToolCall, ToolResult, VerificationResult
from hana_agent_oss.core.registry import ToolRegistry


class ToolVerifier:
    """Verifies deterministic tool effects before the final answer is composed."""

    def __init__(self, tools: ToolRegistry):
        self.tools = tools

    def verify(self, call: ToolCall, result: ToolResult) -> VerificationResult:
        if not result.ok:
            return VerificationResult(False, "tool_result", "Tool failed before verification.", {"error": result.error})

        if call.tool == "file.write":
            return self._verify_file_content(call, mode="write")

        if call.tool == "file.append":
            return self._verify_file_content(call, mode="append")

        if call.tool == "file.read":
            content = result.output.get("content")
            return VerificationResult(content is not None, "tool_result", "Read result returned content.", {"has_content": content is not None})

        if call.tool == "file.exists":
            return VerificationResult(True, "tool_result", "Path existence was checked.", result.output)

        if call.tool == "file.verify_content":
            return VerificationResult(result.ok, "tool_result", result.error or "Content verification passed.", result.output)

        return VerificationResult(True, "tool_result", "No extra verification required for this tool.", {"tool": call.tool})

    def _verify_file_content(self, call: ToolCall, *, mode: str) -> VerificationResult:
        expected = str(call.args.get("content") or "")
        if expected == "":
            return VerificationResult(True, "empty_content", f"File {mode} had empty content; tool result is the verification source.")

        verification_call = ToolCall(
            tool="file.verify_content",
            args={"path": call.args.get("path"), "contains": expected},
            reason=f"Verify file.{mode} effect.",
            risk="low",
        )
        verification_result = self.tools.execute(verification_call)
        return VerificationResult(
            verification_result.ok,
            "file.verify_content",
            verification_result.error or f"File {mode} content verified.",
            verification_result.output,
        )
