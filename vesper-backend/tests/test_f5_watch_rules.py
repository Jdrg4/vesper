"""Reglas de vigilancia y scheduler (F5).

Ningun test arranca el agente: `enqueue_review_job` se sustituye por un no-op.
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.exc import IntegrityError

from src.review_jobs.constants import TaskType
from src.triggers import services as triggers_svc
from src.triggers.models import WatchRule
from tests.test_f4_review_jobs import _make_repo, _register


async def _noop(*args, **kwargs):
    return None


@pytest.fixture
def _sin_encolar(monkeypatch):
    """Evita que el tick lance agentes de verdad."""
    monkeypatch.setattr(triggers_svc, "enqueue_review_job", _noop)


async def _regla(db, tenant_id, repo, **kwargs) -> WatchRule:
    defaults = {"task_type": TaskType.security, "cron": "0 3 * * *", "enabled": True}
    defaults.update(kwargs)
    rule = WatchRule(tenant_id=tenant_id, repository_id=repo.id, **defaults)
    rule.next_run_at = triggers_svc.compute_next_run(rule.cron, enabled=rule.enabled)
    db.add(rule)
    await db.commit()
    return rule


# ------------------------------------------------------------------  Modelo


async def test_una_regla_por_repo_y_tarea(client, db_session):
    """Dos cadencias para la misma tarea es una ambiguedad que nadie necesita."""
    auth = await _register(client, "wr")
    repo = await _make_repo(db_session, auth["tenant_id"])

    await _regla(db_session, auth["tenant_id"], repo)

    db_session.add(
        WatchRule(
            tenant_id=auth["tenant_id"],
            repository_id=repo.id,
            task_type=TaskType.security,
            on_push=True,
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.commit()


# ---------------------------------------------------------  compute_next_run


def test_compute_next_run_sin_cron_es_none():
    assert triggers_svc.compute_next_run(None, enabled=True) is None


def test_compute_next_run_deshabilitada_es_none():
    assert triggers_svc.compute_next_run("0 3 * * *", enabled=False) is None


def test_compute_next_run_avanza_desde_ahora():
    desde = datetime(2026, 8, 3, 10, 0, tzinfo=UTC)
    assert triggers_svc.compute_next_run("0 3 * * *", enabled=True, desde=desde) == datetime(
        2026, 8, 4, 3, 0, tzinfo=UTC
    )


def test_compute_next_run_con_cron_invalido_es_422():
    from src.core.exceptions import ValidationDomainError

    with pytest.raises(ValidationDomainError):
        triggers_svc.compute_next_run("esto no es cron", enabled=True)


# ------------------------------------------------------------------  due_rules


async def test_due_rules_solo_devuelve_vencidas(client, db_session):
    auth = await _register(client, "due")
    repo = await _make_repo(db_session, auth["tenant_id"])
    rule = await _regla(db_session, auth["tenant_id"], repo)

    assert await triggers_svc.due_rules(db_session) == []

    futuro = rule.next_run_at + timedelta(minutes=1)
    vencidas = await triggers_svc.due_rules(db_session, ahora=futuro)
    assert [r.id for r in vencidas] == [rule.id]


async def test_due_rules_ignora_deshabilitadas_y_sin_cron(client, db_session):
    auth = await _register(client, "due2")
    repo = await _make_repo(db_session, auth["tenant_id"])

    await _regla(db_session, auth["tenant_id"], repo, task_type=TaskType.quality, enabled=False)
    await _regla(
        db_session, auth["tenant_id"], repo, task_type=TaskType.docs, cron=None, on_push=True
    )

    lejos = datetime(2030, 1, 1, tzinfo=UTC)
    assert await triggers_svc.due_rules(db_session, ahora=lejos) == []


# -----------------------------------------------------------------------  tick


async def test_el_tick_crea_job_y_avanza_next_run(client, db_session, _sin_encolar):
    auth = await _register(client, "tick")
    repo = await _make_repo(db_session, auth["tenant_id"])
    rule = await _regla(db_session, auth["tenant_id"], repo)
    anterior = rule.next_run_at

    creados = await triggers_svc.tick(db_session, ahora=anterior + timedelta(minutes=1))

    assert creados == 1
    await db_session.refresh(rule)
    assert rule.next_run_at > anterior
    assert rule.last_run_at is not None


async def test_el_job_del_tick_lleva_trigger_cron(client, db_session, _sin_encolar):
    from sqlalchemy import select

    from src.review_jobs.models import ReviewJob

    auth = await _register(client, "tick-trigger")
    repo = await _make_repo(db_session, auth["tenant_id"])
    rule = await _regla(db_session, auth["tenant_id"], repo)

    await triggers_svc.tick(db_session, ahora=rule.next_run_at + timedelta(minutes=1))

    jobs = list(
        (
            await db_session.execute(
                select(ReviewJob).where(ReviewJob.tenant_id == auth["tenant_id"])
            )
        )
        .scalars()
        .all()
    )
    assert len(jobs) == 1
    assert jobs[0].trigger.value == "cron"
    assert jobs[0].ref == repo.default_branch


async def test_dos_ticks_seguidos_no_duplican(client, db_session, _sin_encolar):
    """El segundo tick no encuentra la regla vencida: `next_run_at` ya avanzo."""
    auth = await _register(client, "tick2")
    repo = await _make_repo(db_session, auth["tenant_id"])
    rule = await _regla(db_session, auth["tenant_id"], repo)
    ahora = rule.next_run_at + timedelta(minutes=1)

    assert await triggers_svc.tick(db_session, ahora=ahora) == 1
    assert await triggers_svc.tick(db_session, ahora=ahora) == 0


async def test_el_tick_respeta_el_debounce(client, db_session, _sin_encolar):
    """Con un job ya en vuelo para (repo, tarea), el cron no encola otro."""
    from src.review_jobs.constants import JobStatus
    from src.review_jobs.models import ReviewJob
    from src.tenants.models import Tenant

    auth = await _register(client, "tick-debounce")
    repo = await _make_repo(db_session, auth["tenant_id"])
    tenant = await db_session.get(Tenant, auth["tenant_id"])
    rule = await _regla(db_session, auth["tenant_id"], repo)

    db_session.add(
        ReviewJob(
            tenant_id=tenant.id,
            repository_id=repo.id,
            task_type=TaskType.security,
            status=JobStatus.running,
            model=tenant.developer_model,
        )
    )
    await db_session.commit()

    assert await triggers_svc.tick(db_session, ahora=rule.next_run_at + timedelta(minutes=1)) == 0
    # Pero el reloj avanza igual: si no, reintentaria cada minuto para siempre.
    await db_session.refresh(rule)
    assert rule.last_run_at is not None


async def test_el_tick_no_propaga_la_excepcion_de_cuota(client, db_session, _sin_encolar):
    """Un disparo automatico no tiene a quien devolverle un 429."""
    from src.review_jobs.constants import JobStatus
    from src.review_jobs.models import ReviewJob
    from src.tenants.constants import PLAN_QUOTAS, Plan
    from src.tenants.models import Tenant

    auth = await _register(client, "tick-cuota")
    repo = await _make_repo(db_session, auth["tenant_id"])
    tenant = await db_session.get(Tenant, auth["tenant_id"])
    rule = await _regla(db_session, auth["tenant_id"], repo)

    for _ in range(PLAN_QUOTAS[Plan.free]["max_jobs_per_day"]):
        db_session.add(
            ReviewJob(
                tenant_id=tenant.id,
                repository_id=repo.id,
                task_type=TaskType.quality,
                status=JobStatus.completed,
                model=tenant.developer_model,
            )
        )
    await db_session.commit()

    assert await triggers_svc.tick(db_session, ahora=rule.next_run_at + timedelta(minutes=1)) == 0


async def test_el_tick_ignora_repos_no_enrolados(client, db_session, _sin_encolar):
    auth = await _register(client, "tick-noenrol")
    repo = await _make_repo(db_session, auth["tenant_id"])
    rule = await _regla(db_session, auth["tenant_id"], repo)
    repo.is_enrolled = False
    await db_session.commit()

    assert await triggers_svc.tick(db_session, ahora=rule.next_run_at + timedelta(minutes=1)) == 0


# --------------------------------------------------------------  Jobs colgados


async def test_el_tick_recoge_jobs_colgados(client, db_session, _sin_encolar):
    """Un job `running` huerfano bloquearia el debounce de su repo para siempre."""
    from datetime import timedelta

    from src.review_jobs.constants import JobStatus
    from src.review_jobs.models import ReviewJob
    from src.review_jobs.services import STALE_JOB_SECONDS
    from src.tenants.models import Tenant

    auth = await _register(client, "reaper")
    repo = await _make_repo(db_session, auth["tenant_id"])
    tenant = await db_session.get(Tenant, auth["tenant_id"])
    rule = await _regla(db_session, auth["tenant_id"], repo)

    colgado = ReviewJob(
        tenant_id=tenant.id,
        repository_id=repo.id,
        task_type=TaskType.security,
        status=JobStatus.running,
        model=tenant.developer_model,
        started_at=datetime.now(UTC) - timedelta(seconds=STALE_JOB_SECONDS + 60),
    )
    db_session.add(colgado)
    await db_session.commit()

    # El tick lo recoge y por tanto el debounce ya no lo ve: encola de nuevo.
    creados = await triggers_svc.tick(db_session, ahora=rule.next_run_at + timedelta(minutes=1))

    await db_session.refresh(colgado)
    assert colgado.status == JobStatus.failed
    assert creados == 1


async def test_el_reaper_no_toca_jobs_recientes(client, db_session, _sin_encolar):
    """Un job que lleva dos minutos corriendo esta vivo, no colgado."""
    from datetime import timedelta

    from src.review_jobs.constants import JobStatus
    from src.review_jobs.models import ReviewJob
    from src.review_jobs.services import reap_stale_jobs
    from src.tenants.models import Tenant

    auth = await _register(client, "reaper2")
    repo = await _make_repo(db_session, auth["tenant_id"])
    tenant = await db_session.get(Tenant, auth["tenant_id"])

    vivo = ReviewJob(
        tenant_id=tenant.id,
        repository_id=repo.id,
        task_type=TaskType.security,
        status=JobStatus.running,
        model=tenant.developer_model,
        started_at=datetime.now(UTC) - timedelta(minutes=2),
    )
    db_session.add(vivo)
    await db_session.commit()

    assert await reap_stale_jobs(db_session) == 0
    await db_session.refresh(vivo)
    assert vivo.status == JobStatus.running


# ------------------------------------------------------------------------  CRUD


async def test_crud_de_reglas(client, db_session):
    auth = await _register(client, "crud")
    repo = await _make_repo(db_session, auth["tenant_id"])
    h = {"Cookie": auth["cookie"]}

    r = await client.post(
        f"/api/v1/repositories/{repo.id}/watch-rules",
        json={"task_type": "security", "cron": "0 3 * * *"},
        headers=h,
    )
    assert r.status_code == 201, r.text
    rule_id = r.json()["id"]
    assert r.json()["next_run_at"] is not None

    r = await client.get(f"/api/v1/repositories/{repo.id}/watch-rules", headers=h)
    assert [x["id"] for x in r.json()] == [rule_id]

    r = await client.patch(f"/api/v1/watch-rules/{rule_id}", json={"enabled": False}, headers=h)
    assert r.status_code == 200, r.text
    # Deshabilitar apaga el reloj: si no, al reactivarla dispararia de golpe.
    assert r.json()["next_run_at"] is None

    r = await client.delete(f"/api/v1/watch-rules/{rule_id}", headers=h)
    assert r.status_code == 204

    r = await client.get(f"/api/v1/repositories/{repo.id}/watch-rules", headers=h)
    assert r.json() == []


async def test_reactivar_reprograma_el_reloj(client, db_session):
    auth = await _register(client, "crud-react")
    repo = await _make_repo(db_session, auth["tenant_id"])
    h = {"Cookie": auth["cookie"]}

    r = await client.post(
        f"/api/v1/repositories/{repo.id}/watch-rules",
        json={"task_type": "deps", "cron": "0 3 * * *", "enabled": False},
        headers=h,
    )
    assert r.json()["next_run_at"] is None

    r = await client.patch(
        f"/api/v1/watch-rules/{r.json()['id']}", json={"enabled": True}, headers=h
    )
    assert r.json()["next_run_at"] is not None


async def test_regla_solo_on_push_es_valida(client, db_session):
    auth = await _register(client, "crud-push")
    repo = await _make_repo(db_session, auth["tenant_id"])

    r = await client.post(
        f"/api/v1/repositories/{repo.id}/watch-rules",
        json={"task_type": "quality", "on_push": True},
        headers={"Cookie": auth["cookie"]},
    )
    assert r.status_code == 201, r.text
    assert r.json()["cron"] is None
    assert r.json()["next_run_at"] is None


async def test_regla_duplicada_es_409_no_500(client, db_session):
    """El UNIQUE de la BD no puede llegar al usuario como fallo del servidor."""
    auth = await _register(client, "crud-dup")
    repo = await _make_repo(db_session, auth["tenant_id"])
    h = {"Cookie": auth["cookie"]}
    body = {"task_type": "security", "on_push": True}

    assert (
        await client.post(f"/api/v1/repositories/{repo.id}/watch-rules", json=body, headers=h)
    ).status_code == 201

    r = await client.post(f"/api/v1/repositories/{repo.id}/watch-rules", json=body, headers=h)
    assert r.status_code == 409, r.text
    assert r.json()["code"] == "conflict"


async def test_cron_invalido_es_422(client, db_session):
    auth = await _register(client, "cronmalo")
    repo = await _make_repo(db_session, auth["tenant_id"])

    r = await client.post(
        f"/api/v1/repositories/{repo.id}/watch-rules",
        json={"task_type": "security", "cron": "esto no es cron"},
        headers={"Cookie": auth["cookie"]},
    )
    assert r.status_code == 422


async def test_aislamiento_reglas_entre_tenants(client, db_session):
    """B no ve ni toca las reglas de A. 404, no 403: a B no le consta que existan."""
    a = await _register(client, "iso-a")
    b = await _register(client, "iso-b")
    repo_a = await _make_repo(db_session, a["tenant_id"])

    r = await client.post(
        f"/api/v1/repositories/{repo_a.id}/watch-rules",
        json={"task_type": "security", "cron": "0 3 * * *"},
        headers={"Cookie": a["cookie"]},
    )
    rule_id = r.json()["id"]

    hb = {"Cookie": b["cookie"]}
    assert (
        await client.get(f"/api/v1/repositories/{repo_a.id}/watch-rules", headers=hb)
    ).status_code == 404
    assert (
        await client.patch(f"/api/v1/watch-rules/{rule_id}", json={"enabled": False}, headers=hb)
    ).status_code == 404
    assert (await client.delete(f"/api/v1/watch-rules/{rule_id}", headers=hb)).status_code == 404


async def test_crear_regla_en_repo_de_otro_tenant_es_404(client, db_session):
    a = await _register(client, "iso2-a")
    b = await _register(client, "iso2-b")
    repo_a = await _make_repo(db_session, a["tenant_id"])

    r = await client.post(
        f"/api/v1/repositories/{repo_a.id}/watch-rules",
        json={"task_type": "security", "on_push": True},
        headers={"Cookie": b["cookie"]},
    )
    assert r.status_code == 404


async def test_reglas_requieren_autenticacion(client):
    """Sin `_register` previo el cliente no tiene cookie en su jar."""
    import uuid

    r = await client.get(f"/api/v1/repositories/{uuid.uuid4()}/watch-rules")
    assert r.status_code == 401
