class FailureTriage:
    """Non-mutating failure classifier used before development repair."""

    def classify(self, job, test_result):
        summary = test_result.get("summary", "")
        if "400 Bad Request" in summary and "OPTIONS" in summary:
            return {
                "classification": "incorrect_test_expectation",
                "confidence": "high",
                "reason": "Starlette CORSMiddleware rejects disallowed preflight origins with 400 and omits permission headers.",
                "recommended_action": "Update contradictory tests to expect 400 without permission headers; do not weaken production CORS behavior.",
            }
        classification = "environment_problem" if test_result.get("timed_out") or test_result.get("returncode") in (126, 127) else "implementation_or_test_failure"
        return {
            "classification": classification,
            "confidence": "low",
            "reason": summary[-1200:],
            "recommended_action": "Inspect the failing test and implementation, then verify expected behavior against framework documentation.",
        }
