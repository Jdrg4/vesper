"""0004_f3_repo_unique_per_tenant

La unicidad de `repositories.github_id` pasa a ser POR TENANT. El UNIQUE global
impedia que dos tenants vigilaran el mismo repo de GitHub y hacia que el sync
del segundo encontrara y mutara la fila del primero.

Revision ID: 73f07073c9ac
Revises: 1ffbe5216167
Create Date: 2026-07-28 16:05:56.940912

"""

from collections.abc import Sequence
from typing import Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "73f07073c9ac"
down_revision: Union[str, None] = "1ffbe5216167"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint("repositories_github_id_key", "repositories", type_="unique")
    op.create_unique_constraint(
        "uq_repositories_tenant_gh", "repositories", ["tenant_id", "github_id"]
    )


def downgrade() -> None:
    # Nota: si a estas alturas hay dos tenants con el mismo `github_id`, este
    # downgrade falla al recrear el UNIQUE global. Es lo correcto: perder filas
    # en silencio seria peor.
    op.drop_constraint("uq_repositories_tenant_gh", "repositories", type_="unique")
    op.create_unique_constraint("repositories_github_id_key", "repositories", ["github_id"])
