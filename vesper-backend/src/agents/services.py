"""Logica de negocio del dominio `agents`.

F6: CRUD de `AgentConfig` (siempre scoped por tenant), listar `SkillTemplate`
(catalogo global), listar `ModelCatalog` (catalogo global).

F4 (parcial): el agent runner (`src.agents.runner`) vive aqui. No es CRUD;
es el motor que spawnea `opencode serve`. Ver `agent-runner` agent para el
flujo completo.

La abstraccion `LLMProvider` (`src.agents.llm_provider` en F4) enruta al
endpoint Zen correcto (`/chat/completions` vs `/messages`) segun el modelo
del tenant.
"""

# TODO(F4): implementar `src.agents.runner.OpencodeRunner` y
# `src.agents.llm_provider.LLMProvider`.
# TODO(F6): CRUD de configs + catalogos.
