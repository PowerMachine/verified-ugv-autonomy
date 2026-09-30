# Project Framing

## Research Question

Under SLO, latency, safety, and verification constraints, what level of autonomy can be granted to AI-generated action candidates in a physical system?

## Initial Milestone

The initial implementation is deliberately mock-first:

1. Pydantic schemas
2. Mock model client
3. Mock runtime mission
4. Verifier pipeline
5. Promotion manager
6. JSON latency benchmark
7. ROS discovery in read-only/stub mode

## Non-Goals For This Milestone

- No direct LLM motor control
- No physical `/cmd_vel` publication
- No hardcoded ROS topic names
- No hardcoded model server addresses or credentials
- No large model downloads
