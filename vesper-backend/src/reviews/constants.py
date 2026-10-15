"""Constantes del dominio `reviews`."""

# Limite de comentarios inline por review. GitHub tolera muchos, pero un
# review con 500 comentarios es noise para el tenant_admin. Truncar y
# resumir.
MAX_INLINE_COMMENTS_PER_REVIEW = 30

# TODO(F7): ajustar segun feedback.
