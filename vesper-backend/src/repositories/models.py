from sqlalchemy import BigInteger, Boolean, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from src.core.database import Base
from src.shared.mixins import TenantMixin, TimestampMixin, UUIDMixin


class TenantInstallation(TenantMixin, UUIDMixin, TimestampMixin, Base):
    __tablename__ = "tenant_installations"

    # UNIQUE global a proposito: una instalacion de GitHub App pertenece a una
    # sola cuenta y por tanto a un solo tenant. Es la ultima linea de defensa
    # contra que un tenant reclame la instalacion de otro (y con ella los
    # installation tokens de sus repos).
    installation_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False)
    installed_by: Mapped[str | None] = mapped_column(String(128), nullable=True)


class Repository(TenantMixin, UUIDMixin, TimestampMixin, Base):
    __tablename__ = "repositories"

    # La unicidad de `github_id` es POR TENANT, no global: dos tenants pueden
    # tener acceso legitimo al mismo repo de GitHub (un contractor en dos orgs,
    # una org y un fork). Con el UNIQUE global, el sync del segundo tenant
    # encontraba la fila del primero y la mutaba.
    __table_args__ = (UniqueConstraint("tenant_id", "github_id", name="uq_repositories_tenant_gh"),)

    installation_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("tenant_installations.installation_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    github_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    default_branch: Mapped[str] = mapped_column(String(128), default="main", nullable=False)
    private: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_enrolled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
