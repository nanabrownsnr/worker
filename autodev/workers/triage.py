import json
import logging
import urllib.request

logger = logging.getLogger(__name__)


class FailureTriage:
    """Non-mutating failure classifier used before development repair."""

    def __init__(self, settings=None):
        self.s = settings

    def classify(self, job, test_result):
        summary = test_result.get("summary", "")
        # Framework contract takes precedence over model advice for this known case.
        if "400 Bad Request" in summary and "OPTIONS" in summary:
            return {
                "classification": "incorrect_test_expectation",
                "confidence": "high",
                "reason": "Starlette CORSMiddleware rejects disallowed preflight origins with 400 and omits permission headers.",
                "recommended_action": "Update contradictory tests to expect 400 without permission headers; do not weaken production CORS behavior.",
            }
        if self.s:
            try:
                return self._model_classify(job, test_result)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Model triage unavailable; using deterministic fallback: %s", exc)
        classification = "environment_problem" if test_result.get("timed_out") or test_result.get("returncode") in (126, 127) else "implementation_or_test_failure"
        return {
            "classification": classification,
            "confidence": "low",
            "reason": summary[-1200:],
            "recommended_action": "Inspect the failing test and implementation, then verify expected behavior against framework documentation.",
        }

    def _model_classify(self, job, test_result):
        prompt = ("Classify this software test failure without editing files. Return JSON only with keys "
                  "classification, confidence, reason, recommended_action. Classifications are "
                  "implementation_defect, incorrect_test_expectation, environment_problem, ambiguous. "
                  "The original task is:\n" + job.prompt + "\nTest evidence:\n" + test_result.get("summary", "")[-6000:])
        if self.s.triage_model.startswith("nimble"):
            return self._nimble_classify(prompt)
        endpoint = self.s.hermes_endpoint.rstrip("/") + "/chat/completions"
        payload = json.dumps({"model": self.s.triage_model, "temperature": 0, "messages": [{"role": "user", "content": prompt}]}).encode()
        request = urllib.request.Request(endpoint, data=payload, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=self.s.triage_timeout_seconds) as response:
            content = json.loads(response.read()).get("choices", [{}])[0].get("message", {}).get("content", "")
        parsed = json.loads(content[content.find("{"):content.rfind("}") + 1])
        return {"classification": parsed["classification"], "confidence": parsed.get("confidence", "unknown"), "reason": parsed.get("reason", ""), "recommended_action": parsed.get("recommended_action", "")}

    def _nimble_classify(self, prompt):
        endpoint = self.s.hermes_endpoint.rstrip("/") + "/systemone"
        payload = {
            "model": self.s.triage_model,
            "state": prompt,
            "questions": {
                "classification": {
                    "type": "choice",
                    "instructions": "Classify the primary cause of the test failure.",
                    "criteria": {
                        "implementation_defect": "The production application implementation is incorrect.",
                        "incorrect_test_expectation": "The test expectation is incorrect or conflicts with the framework contract.",
                        "environment_problem": "The runtime, dependency, or environment is incorrect.",
                        "ambiguous": "The evidence is insufficient to classify safely.",
                    },
                },
                "repair_scope": {
                    "type": "choice",
                    "instructions": "What should an automated repair be allowed to modify?",
                    "criteria": {
                        "production_code": "Production application code may be modified.",
                        "tests_only": "Only tests may be modified; preserve production behavior.",
                        "environment_only": "Only dependency or environment configuration may be modified.",
                        "none": "Do not modify automatically; require review.",
                    },
                },
            },
        }
        request = urllib.request.Request(endpoint, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=self.s.triage_timeout_seconds) as response:
            answers = json.loads(response.read()).get("answers", {})
        classification = answers.get("classification", {})
        scope = answers.get("repair_scope", {})
        return {
            "classification": classification.get("choice", "ambiguous"),
            "confidence": classification.get("confidence", "unknown"),
            "repair_scope": scope.get("choice", "none"),
            "reason": "Nimble structured classification",
            "recommended_action": "Follow the selected repair scope; preserve production behavior for tests_only.",
        }
