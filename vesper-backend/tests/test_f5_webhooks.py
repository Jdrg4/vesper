"""Webhook de GitHub (F5).

Ninguno golpea GitHub: los payloads se firman a mano con el secreto de test.
"""

import hashlib
import hmac
import json

import pytest
from sqlalchemy import select

from src.core.config import settings
from src.review_jobs.constants import TaskType
from src.review_jobs.models import ReviewJob
from src.triggers import services as triggers_svc
from src.triggers.models import WatchRule
from tests.test_f4_review_jobs import _make_repo, _register

SECRETO = "secreto-de-test"  # pragma: allowlist secret


@pytest.fixture(autouse=True)
def _con_secreto(monkeypatch):
    monkeypatch.setattr(settings, "github_webhook_secret", SECRETO, raising=False)


@pytest.fixture(autouse=True)
def _sin_encolar(monkeypatch):
    """El webhook no debe arrancar agentes de verdad en los tests."""

    async def _noop(*args, **kwargs):
        return None

    monkeypatch.setattr("src.webhooks.services.enqueue_review_job", _noop)
    monkeypatch.setattr(triggers_svc, "enqueue_review_job", _noop)


def _firmar(body: bytes) -> str:
    return "sha256=" + hmac.new(SECRETO.encode(), body, hashlib.sha256).hexdigest()


def _payload(repo, installation_id, *, ref=None, sender="alice", sender_type="User") -> dict:
    return {
        "ref": ref or f"refs/heads/{repo.default_branch}",
        "installation": {"id": installation_id},
        "repository": {"id": repo.github_id, "full_name": repo.full_name},
        "sender": {"login": sender, "type": sender_type},
    }


async def _post(client, payload: dict, *, firma="auto", evento="push"):
    body = json.dumps(payload).encode()
    headers = {"X-GitHub-Event": evento, "Content-Type": "application/json"}
    if firma == "auto":
        headers["X-Hub-Signature-256"] = _firmar(body)
    elif firma is not None:
        headers["X-Hub-Signature-256"] = firma
    return await client.post("/api/v1/webhooks/github", content=body, headers=headers)


async def _regla_on_push(db, tenant_id, repo, task_type=TaskType.security) -> WatchRule:
    rule = WatchRule(tenant_id=tenant_id, repository_id=repo.id, task_type=task_type, on_push=True)
    db.add(rule)
    await db.commit()
    return rule


async def _jobs(db, tenant_id) -> list[ReviewJob]:
    q = select(ReviewJob).where(ReviewJob.tenant_id == tenant_id)
    return list((await db.execute(q)).scalars().all())


# --------------------------------------------------------------------  Firma


async def test_sin_firma_es_401(client, db_session):
    auth = await _register(client, "wh")
    repo = await _make_repo(db_session, auth["tenant_id"])
    r = await _post(client, _payload(repo, repo.installation_id), firma=None)
    assert r.status_code == 401


async def test_firma_invalida_es_401(client, db_session):
    auth = await _register(client, "wh2")
    repo = await _make_repo(db_session, auth["tenant_id"])
    r = await _post(client, _payload(repo, repo.installation_id), firma="sha256=deadbeef")
    assert r.status_code == 401


async def test_firma_de_otro_secreto_es_401(client, db_session):
    auth = await _register(client, "wh2b")
    repo = await _make_repo(db_session, auth["tenant_id"])
    body = json.dumps(_payload(repo, repo.installation_id)).encode()
    otra = "sha256=" + hmac.new(b"otro-secreto", body, hashlib.sha256).hexdigest()
    r = await _post(client, _payload(repo, repo.installation_id), firma=otra)
    assert r.status_code == 401


async def test_sin_secreto_configurado_es_503(client, db_session, monkeypatch):
    """Un despliegue mal configurado no acepta eventos. Falla cerrado."""
    monkeypatch.setattr(settings, "github_webhook_secret", "", raising=False)
    auth = await _register(client, "wh3")
    repo = await _make_repo(db_session, auth["tenant_id"])
    r = await _post(client, _payload(repo, repo.installation_id))
    assert r.status_code == 503


# ------------------------------------------------------------------  Despacho


async def test_push_dispara_las_reglas_on_push(client, db_session):
    auth = await _register(client, "wh4")
    repo = await _make_repo(db_session, auth["tenant_id"])
    await _regla_on_push(db_session, auth["tenant_id"], repo)

    r = await _post(client, _payload(repo, repo.installation_id))
    assert r.status_code == 202, r.text

    jobs = await _jobs(db_session, auth["tenant_id"])
    assert len(jobs) == 1
    assert jobs[0].trigger.value == "webhook"
    assert jobs[0].task_type == TaskType.security


async def test_sin_reglas_no_pasa_nada(client, db_session):
    auth = await _register(client, "wh4b")
    repo = await _make_repo(db_session, auth["tenant_id"])

    r = await _post(client, _payload(repo, repo.installation_id))
    assert r.status_code == 202
    assert await _jobs(db_session, auth["tenant_id"]) == []


async def test_regla_deshabilitada_no_dispara(client, db_session):
    auth = await _register(client, "wh4c")
    repo = await _make_repo(db_session, auth["tenant_id"])
    rule = await _regla_on_push(db_session, auth["tenant_id"], repo)
    rule.enabled = False
    await db_session.commit()

    await _post(client, _payload(repo, repo.installation_id))
    assert await _jobs(db_session, auth["tenant_id"]) == []


async def test_regla_solo_cron_no_dispara_en_push(client, db_session):
    """`on_push=False` significa exactamente eso."""
    auth = await _register(client, "wh4d")
    repo = await _make_repo(db_session, auth["tenant_id"])
    db_session.add(
        WatchRule(
            tenant_id=auth["tenant_id"],
            repository_id=repo.id,
            task_type=TaskType.security,
            cron="0 3 * * *",
            on_push=False,
        )
    )
    await db_session.commit()

    await _post(client, _payload(repo, repo.installation_id))
    assert await _jobs(db_session, auth["tenant_id"]) == []


# ---------------------------------------------------------------  Anti-bucle


async def test_push_a_rama_no_default_se_ignora(client, db_session):
    auth = await _register(client, "wh5")
    repo = await _make_repo(db_session, auth["tenant_id"])
    await _regla_on_push(db_session, auth["tenant_id"], repo)

    await _post(client, _payload(repo, repo.installation_id, ref="refs/heads/feature-x"))
    assert await _jobs(db_session, auth["tenant_id"]) == []


async def test_push_de_rama_del_bot_se_ignora(client, db_session):
    """Anti-bucle: cada PR del bot genera un push. Sin esto, no para nunca."""
    auth = await _register(client, "wh6")
    repo = await _make_repo(db_session, auth["tenant_id"], default_branch="vesper/security-x")
    await _regla_on_push(db_session, auth["tenant_id"], repo)

    await _post(client, _payload(repo, repo.installation_id))
    assert await _jobs(db_session, auth["tenant_id"]) == []


async def test_push_del_propio_bot_se_ignora(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "github_app_slug", "vesper-bot", raising=False)
    auth = await _register(client, "wh7")
    repo = await _make_repo(db_session, auth["tenant_id"])
    await _regla_on_push(db_session, auth["tenant_id"], repo)

    await _post(
        client,
        _payload(repo, repo.installation_id, sender="vesper-bot[bot]", sender_type="Bot"),
    )
    assert await _jobs(db_session, auth["tenant_id"]) == []


async def test_otro_bot_cualquiera_si_dispara(client, db_session, monkeypatch):
    """Solo se filtra NUESTRO bot: dependabot es un push legitimo que vigilar."""
    monkeypatch.setattr(settings, "github_app_slug", "vesper-bot", raising=False)
    auth = await _register(client, "wh7b")
    repo = await _make_repo(db_session, auth["tenant_id"])
    await _regla_on_push(db_session, auth["tenant_id"], repo)

    await _post(
        client,
        _payload(repo, repo.installation_id, sender="dependabot[bot]", sender_type="Bot"),
    )
    assert len(await _jobs(db_session, auth["tenant_id"])) == 1


async def test_repo_no_enrolado_se_ignora(client, db_session):
    """La App tiene permiso sobre todos los repos; solo se toca lo enrolado."""
    auth = await _register(client, "wh8")
    repo = await _make_repo(db_session, auth["tenant_id"])
    await _regla_on_push(db_session, auth["tenant_id"], repo)
    repo.is_enrolled = False
    await db_session.commit()

    await _post(client, _payload(repo, repo.installation_id))
    assert await _jobs(db_session, auth["tenant_id"]) == []


async def test_debounce_dos_pushes_un_job(client, db_session):
    auth = await _register(client, "wh9")
    repo = await _make_repo(db_session, auth["tenant_id"])
    await _regla_on_push(db_session, auth["tenant_id"], repo)

    await _post(client, _payload(repo, repo.installation_id))
    await _post(client, _payload(repo, repo.installation_id))

    assert len(await _jobs(db_session, auth["tenant_id"])) == 1


# ------------------------------------------------------------  Multi-tenancy


async def test_instalacion_desconocida_es_202_sin_efectos(client, db_session):
    auth = await _register(client, "wh10")
    repo = await _make_repo(db_session, auth["tenant_id"])
    r = await _post(client, _payload(repo, 999_999_999))
    assert r.status_code == 202
    assert await _jobs(db_session, auth["tenant_id"]) == []


async def test_aislamiento_el_payload_no_decide_el_tenant(client, db_session):
    """A firma un evento de SU instalacion nombrando un repo de B: B no se toca.

    Si esto falla, el tenant se esta resolviendo desde el cuerpo del evento y
    hay una fuga entre tenants — no es un test quisquilloso.
    """
    a = await _register(client, "wh-iso-a")
    b = await _register(client, "wh-iso-b")
    repo_a = await _make_repo(db_session, a["tenant_id"])
    repo_b = await _make_repo(db_session, b["tenant_id"])
    await _regla_on_push(db_session, b["tenant_id"], repo_b)

    # Instalacion de A, repositorio de B.
    r = await _post(client, _payload(repo_b, repo_a.installation_id))

    assert r.status_code == 202
    assert await _jobs(db_session, b["tenant_id"]) == []
    assert await _jobs(db_session, a["tenant_id"]) == []


async def test_dos_tenants_con_el_mismo_repo_solo_dispara_el_dueno(client, db_session):
    """Mismo `github_id` en dos tenants: solo corre el de la instalacion firmante."""
    a = await _register(client, "wh-dup-a")
    b = await _register(client, "wh-dup-b")
    repo_a = await _make_repo(db_session, a["tenant_id"])
    repo_b = await _make_repo(db_session, b["tenant_id"])
    # B tiene enrolado el MISMO repo de GitHub que A.
    repo_b.github_id = repo_a.github_id
    await db_session.commit()

    await _regla_on_push(db_session, a["tenant_id"], repo_a)
    await _regla_on_push(db_session, b["tenant_id"], repo_b)

    await _post(client, _payload(repo_a, repo_a.installation_id))

    assert len(await _jobs(db_session, a["tenant_id"])) == 1
    assert await _jobs(db_session, b["tenant_id"]) == []


# -------------------------------------------------------------  Otros eventos


async def test_pull_request_se_ignora(client, db_session):
    """Materia de F7; hoy se registra y se descarta."""
    auth = await _register(client, "wh11")
    repo = await _make_repo(db_session, auth["tenant_id"])
    await _regla_on_push(db_session, auth["tenant_id"], repo)

    r = await _post(client, _payload(repo, repo.installation_id), evento="pull_request")
    assert r.status_code == 202
    assert r.json()["handled"] is False
    assert await _jobs(db_session, auth["tenant_id"]) == []


async def test_ping_se_ignora(client, db_session):
    """GitHub manda un `ping` al crear el webhook. No puede ser un 500."""
    auth = await _register(client, "wh12")
    repo = await _make_repo(db_session, auth["tenant_id"])
    r = await _post(client, _payload(repo, repo.installation_id), evento="ping")
    assert r.status_code == 202
