ACTION_CANDIDATE_PROMPT = """Return only JSON for an ActionCandidate.
Goal: {goal}
Allowed early actions: stop, wait, inspect_point, return_home, report_only, primitive_sequence.
Never produce direct motor commands.
"""

CRITIC_PROMPT = """Review the candidate for schema, evidence, SLO, and safety risk.
Return a compact JSON report.
"""
