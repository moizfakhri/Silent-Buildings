"""Phase 7 LLM layer: text-to-SQL over the marts, building biographies with verified citations, and retrieval experiments.

Everything runs offline against deterministic stubs; a live Anthropic client is used only when ANTHROPIC_API_KEY is set
(in the environment or in .env). Stub results are harness checks, never model results.
"""
