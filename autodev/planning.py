import json
import urllib.request

from .schemas import Ticket


class ProjectPlanner:
    """Creates a bounded, ordered ticket plan without editing the workspace."""

    def __init__(self, settings):
        self.s = settings

    def plan(self, prompt: str) -> list[Ticket]:
        if not self.s.hermes_endpoint:
            return [Ticket(ticket_id="TKT-001", title="Implement the requested project", goal=prompt, acceptance_criteria=["Implement the requested behavior", "Add meaningful tests", "Run the repository validation commands"])]
        instruction = """Decompose this software project brief into 2-8 ordered implementation tickets. Return JSON only as an array of objects with ticket_id, title, goal, and acceptance_criteria (array of strings). Keep tickets independently testable and incremental. Do not implement anything.\n\nPROJECT BRIEF:\n""" + prompt
        payload = json.dumps({"model": self.s.planner_model, "temperature": 0, "messages": [{"role": "user", "content": instruction}]}).encode()
        request = urllib.request.Request(self.s.hermes_endpoint.rstrip("/") + "/chat/completions", data=payload, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=self.s.triage_timeout_seconds) as response:
            content = json.loads(response.read()).get("choices", [{}])[0].get("message", {}).get("content", "")
        values = json.loads(content[content.find("["):content.rfind("]") + 1])
        return [Ticket.model_validate(value) for value in values[:8]] or self.plan_without_model(prompt)

    @staticmethod
    def plan_without_model(prompt):
        return [Ticket(ticket_id="TKT-001", title="Implement the requested project", goal=prompt, acceptance_criteria=["Implement the requested behavior", "Add meaningful tests", "Run the repository validation commands"])]

    def guidance(self, prompt: str, ticket: Ticket, failures: str) -> str:
        if not self.s.hermes_endpoint:
            return "Re-read the ticket and failing tests, inspect the production code and fix the underlying behavior. Do not add workaround tests or weaken existing tests."
        instruction = ("You are the senior software engineer reviewing a blocked ticket. Return concise repair guidance only; do not edit files. "
                       "Identify the root cause, the likely production files, and the smallest correct repair. Do not recommend weakening tests.\n\n"
                       f"PROJECT:\n{prompt}\nTICKET:\n{ticket.model_dump_json()}\nFAILURES:\n{failures[-8000:]}")
        payload = json.dumps({"model": self.s.planner_model, "temperature": 0, "messages": [{"role": "user", "content": instruction}]}).encode()
        request = urllib.request.Request(self.s.hermes_endpoint.rstrip("/") + "/chat/completions", data=payload, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=self.s.triage_timeout_seconds) as response:
            return json.loads(response.read()).get("choices", [{}])[0].get("message", {}).get("content", "")[-6000:]
