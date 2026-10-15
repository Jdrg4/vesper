"""Logica de negocio del dominio `reviews`.

F7: `run_review(job_id)` — segunda sesion opencode con `reviewer_model` del
tenant. Lee el diff del job, produce observaciones, abre **GitHub review**
(comentarios inline + summary) via GitHub App `POST /repos/.../pulls/<n>/reviews`.
NO abre otro PR.

Multi-agente reviewer: esto es el equivalente servidor-side del
*un modelo desarrolla, otro revisa*.
"""

# TODO(F7): implementar `run_review`. Ver `agent-runner` agent.
