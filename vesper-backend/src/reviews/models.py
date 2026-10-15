"""Modelos del dominio `reviews`.

F7: `Review` (UUIDMixin, TimestampMixin, TenantMixin) — pasada de revision
sobre un PR abierto por un `ReviewJob`. FK a `review_jobs.id` ON DELETE
CASCADE. `reviewer_model`, `status` (running/completed/failed), `pr_number`,
`github_review_id` (int, id de la review en GitHub), `summary` (texto).
Tabla de tenant.
"""

# TODO(F7): declarar `Review`.
