import uuid
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.config import MAX_DOCUMENT_CHARS
from app.db import get_db
from app.harness import AIHarness
from app.models import (
    AuditEvent, Chunk, Document, HarnessRun, KnowledgeBase, Membership,
    OrgUnit, Tenant, User, WikiEntity, WikiRelation,
)
from app.ollama import OllamaUnavailable
from app.permissions import (
    accessible_unit_ids, current_user, get_accessible_kb, membership_for,
    require_kb_admin, require_kb_writer,
)
from app.security import create_access_token, hash_password, verify_password


app = FastAPI(
    title="Knowledge Wiki SaaS",
    description="Multi-tenant knowledge bases with grounded RAG and an LLM Wiki.",
    version="0.1.0",
)
harness = AIHarness()
STATIC_DIR = Path(__file__).parent / "static"


class LoginInput(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=256)


class TenantInput(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    slug: str = Field(min_length=2, max_length=120, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    admin_email: EmailStr
    admin_name: str = Field(min_length=1, max_length=160)
    admin_password: str = Field(min_length=12, max_length=256)


class OrgUnitInput(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    parent_id: uuid.UUID | None = None


class UserInput(BaseModel):
    email: EmailStr
    display_name: str = Field(min_length=1, max_length=160)
    password: str = Field(min_length=12, max_length=256)
    role: str = Field(default="member", pattern="^(member|unit_admin|tenant_admin)$")
    unit_id: uuid.UUID | None = None


class KnowledgeBaseInput(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    description: str = Field(default="", max_length=2000)
    unit_id: uuid.UUID | None = None


class DocumentInput(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    content: str = Field(min_length=1)
    source_name: str = Field(default="", max_length=300)


class AskInput(BaseModel):
    question: str = Field(min_length=2, max_length=4000)


def audit(
    db: Session,
    *,
    actor_id: uuid.UUID | None,
    tenant_id: uuid.UUID | None,
    action: str,
    resource_type: str = "",
    resource_id: str = "",
    details: dict[str, Any] | None = None,
) -> None:
    db.add(AuditEvent(
        tenant_id=tenant_id,
        actor_id=actor_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        details=details or {},
    ))


def public_user(user: User) -> dict[str, Any]:
    return {
        "id": str(user.id),
        "email": user.email,
        "display_name": user.display_name,
        "is_platform_admin": user.is_platform_admin,
        "is_active": user.is_active,
    }


def public_membership(db: Session, membership: Membership) -> dict[str, Any]:
    tenant = db.get(Tenant, membership.tenant_id)
    unit = db.get(OrgUnit, membership.unit_id) if membership.unit_id else None
    return {
        "tenant_id": str(membership.tenant_id),
        "tenant_name": tenant.name if tenant else "",
        "tenant_slug": tenant.slug if tenant else "",
        "role": membership.role,
        "unit_id": str(membership.unit_id) if membership.unit_id else None,
        "unit_name": unit.name if unit else None,
    }


def validate_unit(db: Session, tenant_id: uuid.UUID, unit_id: uuid.UUID) -> OrgUnit:
    unit = db.scalar(select(OrgUnit).where(OrgUnit.id == unit_id, OrgUnit.tenant_id == tenant_id))
    if not unit:
        raise HTTPException(status_code=404, detail="Organization unit not found.")
    return unit


def require_unit_scope(db: Session, membership: Membership, unit_id: uuid.UUID) -> None:
    if unit_id not in accessible_unit_ids(db, membership):
        raise HTTPException(status_code=403, detail="Organization unit is outside your scope.")


@app.get("/", include_in_schema=False)
def home() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/healthz")
def health(db: Session = Depends(get_db)) -> dict[str, str]:
    db.execute(text("SELECT 1"))
    return {"status": "ok", "database": "ok"}


@app.post("/api/v1/auth/token")
def login(payload: LoginInput, db: Session = Depends(get_db)) -> dict[str, Any]:
    email = payload.email.strip().lower()
    user = db.scalar(select(User).where(User.email == email, User.is_active.is_(True)))
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Email or password is incorrect.")
    return {
        "access_token": create_access_token(str(user.id)),
        "token_type": "bearer",
        "user": public_user(user),
        "memberships": [
            public_membership(db, membership)
            for membership in db.scalars(
                select(Membership).where(Membership.user_id == user.id, Membership.is_active.is_(True))
            ).all()
        ],
    }


@app.get("/api/v1/me")
def me(user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    memberships = db.scalars(
        select(Membership).where(Membership.user_id == user.id, Membership.is_active.is_(True))
    ).all()
    return {
        "user": public_user(user),
        "memberships": [public_membership(db, item) for item in memberships],
    }


@app.get("/api/v1/tenants")
def list_tenants(user: User = Depends(current_user), db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    if not user.is_platform_admin:
        raise HTTPException(status_code=403, detail="Platform administrator role required.")
    rows = db.scalars(select(Tenant).order_by(Tenant.name)).all()
    return [{"id": str(row.id), "name": row.name, "slug": row.slug, "is_active": row.is_active} for row in rows]


@app.post("/api/v1/tenants", status_code=201)
def create_tenant(
    payload: TenantInput,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    if not user.is_platform_admin:
        raise HTTPException(status_code=403, detail="Platform administrator role required.")
    slug = payload.slug.strip().lower()
    email = payload.admin_email.strip().lower()
    if db.scalar(select(Tenant.id).where(Tenant.slug == slug)):
        raise HTTPException(status_code=409, detail="Tenant slug is already in use.")
    try:
        admin_password_hash = hash_password(payload.admin_password)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    admin = db.scalar(select(User).where(User.email == email))
    if admin and db.scalar(select(Membership.id).where(Membership.user_id == admin.id)):
        raise HTTPException(status_code=409, detail="That account already belongs to a tenant.")
    if not admin:
        admin = User(
            email=email,
            display_name=payload.admin_name.strip(),
            password_hash=admin_password_hash,
        )
        db.add(admin)
        db.flush()

    tenant = Tenant(name=payload.name.strip(), slug=slug)
    db.add(tenant)
    db.flush()
    root = OrgUnit(tenant_id=tenant.id, name="总部")
    db.add(root)
    db.flush()
    db.add(Membership(
        tenant_id=tenant.id,
        user_id=admin.id,
        unit_id=root.id,
        role="tenant_admin",
    ))
    audit(
        db,
        actor_id=user.id,
        tenant_id=tenant.id,
        action="tenant.created",
        resource_type="tenant",
        resource_id=str(tenant.id),
        details={"slug": slug, "admin_email": email},
    )
    db.commit()
    return {
        "id": str(tenant.id),
        "name": tenant.name,
        "slug": tenant.slug,
        "admin": {"id": str(admin.id), "email": admin.email},
        "root_unit": {"id": str(root.id), "name": root.name},
    }


@app.get("/api/v1/tenants/{tenant_id}/org-units")
def list_units(
    tenant_id: uuid.UUID,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    membership = membership_for(db, user, tenant_id)
    query = select(OrgUnit).where(OrgUnit.tenant_id == tenant_id).order_by(OrgUnit.name)
    if membership.role != "tenant_admin":
        allowed = accessible_unit_ids(db, membership)
        query = query.where(OrgUnit.id.in_(allowed)) if allowed else query.where(OrgUnit.id.is_(None))
    units = db.scalars(query).all()
    return [{"id": str(row.id), "name": row.name, "parent_id": str(row.parent_id) if row.parent_id else None} for row in units]


@app.post("/api/v1/tenants/{tenant_id}/org-units", status_code=201)
def create_unit(
    tenant_id: uuid.UUID,
    payload: OrgUnitInput,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    membership = membership_for(db, user, tenant_id)
    parent = None
    if membership.role == "unit_admin":
        if membership.unit_id is None:
            raise HTTPException(status_code=403, detail="Assign an organization unit before managing child units.")
        if payload.parent_id is None:
            raise HTTPException(status_code=403, detail="Unit administrators may only add descendants.")
        require_unit_scope(db, membership, payload.parent_id)
    elif membership.role != "tenant_admin":
        raise HTTPException(status_code=403, detail="Organization administrator role required.")
    if payload.parent_id:
        parent = validate_unit(db, tenant_id, payload.parent_id)
    elif membership.role != "tenant_admin":
        raise HTTPException(status_code=403, detail="Only tenant administrators may create a root unit.")

    unit = OrgUnit(
        tenant_id=tenant_id,
        parent_id=parent.id if parent else None,
        name=payload.name.strip(),
    )
    db.add(unit)
    db.flush()
    audit(db, actor_id=user.id, tenant_id=tenant_id, action="org_unit.created", resource_type="org_unit", resource_id=str(unit.id))
    db.commit()
    return {"id": str(unit.id), "name": unit.name, "parent_id": str(unit.parent_id) if unit.parent_id else None}


@app.get("/api/v1/tenants/{tenant_id}/users")
def list_users(
    tenant_id: uuid.UUID,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    membership = membership_for(db, user, tenant_id)
    query = (
        select(User, Membership)
        .join(Membership, Membership.user_id == User.id)
        .where(Membership.tenant_id == tenant_id, Membership.is_active.is_(True))
        .order_by(User.email)
    )
    if membership.role == "unit_admin":
        allowed = accessible_unit_ids(db, membership)
        query = query.where(Membership.unit_id.in_(allowed)) if allowed else query.where(Membership.unit_id.is_(None))
    elif membership.role != "tenant_admin":
        query = query.where(Membership.user_id == user.id)
    return [
        {
            "id": str(person.id),
            "email": person.email,
            "display_name": person.display_name,
            "role": member.role,
            "unit_id": str(member.unit_id) if member.unit_id else None,
        }
        for person, member in db.execute(query).all()
    ]


@app.post("/api/v1/tenants/{tenant_id}/users", status_code=201)
def create_user(
    tenant_id: uuid.UUID,
    payload: UserInput,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    manager = membership_for(db, user, tenant_id)
    email = payload.email.strip().lower()
    if manager.role == "unit_admin":
        if payload.role != "member" or payload.unit_id is None:
            raise HTTPException(status_code=403, detail="Unit administrators may create members in their own scope.")
        require_unit_scope(db, manager, payload.unit_id)
    elif manager.role != "tenant_admin":
        raise HTTPException(status_code=403, detail="Tenant administrator role required.")
    if not payload.unit_id:
        raise HTTPException(status_code=422, detail="Select an organization unit.")
    validate_unit(db, tenant_id, payload.unit_id)

    person = db.scalar(select(User).where(User.email == email))
    if person:
        if db.scalar(select(Membership.id).where(Membership.tenant_id == tenant_id, Membership.user_id == person.id)):
            raise HTTPException(status_code=409, detail="User is already a member of this tenant.")
    else:
        try:
            password_hash = hash_password(payload.password)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        person = User(email=email, display_name=payload.display_name.strip(), password_hash=password_hash)
        db.add(person)
        db.flush()

    member = Membership(
        tenant_id=tenant_id,
        user_id=person.id,
        unit_id=payload.unit_id,
        role=payload.role,
    )
    db.add(member)
    audit(db, actor_id=user.id, tenant_id=tenant_id, action="user.added", resource_type="user", resource_id=str(person.id), details={"role": payload.role})
    db.commit()
    return {"id": str(person.id), "email": person.email, "display_name": person.display_name, "role": member.role, "unit_id": str(member.unit_id) if member.unit_id else None}


@app.get("/api/v1/tenants/{tenant_id}/knowledge-bases")
def list_knowledge_bases(
    tenant_id: uuid.UUID,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    membership = membership_for(db, user, tenant_id)
    query = select(KnowledgeBase).where(KnowledgeBase.tenant_id == tenant_id).order_by(KnowledgeBase.name)
    if membership.role != "tenant_admin":
        allowed = accessible_unit_ids(db, membership)
        query = query.where((KnowledgeBase.unit_id.is_(None)) | KnowledgeBase.unit_id.in_(allowed)) if allowed else query.where(KnowledgeBase.unit_id.is_(None))
    rows = db.scalars(query).all()
    output = []
    for kb in rows:
        unit = db.get(OrgUnit, kb.unit_id) if kb.unit_id else None
        count = db.scalar(select(func.count(Document.id)).where(Document.knowledge_base_id == kb.id)) or 0
        output.append({
            "id": str(kb.id),
            "name": kb.name,
            "description": kb.description,
            "unit_id": str(kb.unit_id) if kb.unit_id else None,
            "unit_name": unit.name if unit else "租户共享",
            "documents": count,
        })
    return output


@app.post("/api/v1/tenants/{tenant_id}/knowledge-bases", status_code=201)
def create_knowledge_base(
    tenant_id: uuid.UUID,
    payload: KnowledgeBaseInput,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    membership = membership_for(db, user, tenant_id)
    if membership.role not in {"tenant_admin", "unit_admin"}:
        raise HTTPException(status_code=403, detail="Knowledge base administrator role required.")
    if payload.unit_id is None and membership.role != "tenant_admin":
        raise HTTPException(status_code=403, detail="Only tenant administrators may create tenant-wide knowledge bases.")
    if payload.unit_id:
        validate_unit(db, tenant_id, payload.unit_id)
        if membership.role == "unit_admin":
            require_unit_scope(db, membership, payload.unit_id)
    kb = KnowledgeBase(
        tenant_id=tenant_id,
        unit_id=payload.unit_id,
        name=payload.name.strip(),
        description=payload.description.strip(),
        created_by=user.id,
    )
    db.add(kb)
    db.flush()
    audit(db, actor_id=user.id, tenant_id=tenant_id, action="knowledge_base.created", resource_type="knowledge_base", resource_id=str(kb.id))
    db.commit()
    return {"id": str(kb.id), "name": kb.name, "unit_id": str(kb.unit_id) if kb.unit_id else None}


@app.get("/api/v1/tenants/{tenant_id}/knowledge-bases/{kb_id}/documents")
def list_documents(
    tenant_id: uuid.UUID,
    kb_id: uuid.UUID,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    kb, _ = get_accessible_kb(db, user, tenant_id, kb_id)
    rows = db.scalars(
        select(Document).where(
            Document.tenant_id == tenant_id,
            Document.knowledge_base_id == kb.id,
        ).order_by(Document.created_at.desc())
    ).all()
    return [{
        "id": str(row.id),
        "title": row.title,
        "source_name": row.source_name,
        "status": row.status,
        "error_message": row.error_message,
        "created_at": row.created_at.isoformat(),
    } for row in rows]


@app.post("/api/v1/tenants/{tenant_id}/knowledge-bases/{kb_id}/documents", status_code=201)
def add_document(
    tenant_id: uuid.UUID,
    kb_id: uuid.UUID,
    payload: DocumentInput,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    kb, membership = get_accessible_kb(db, user, tenant_id, kb_id)
    require_kb_writer(db, membership, kb)
    content = payload.content.strip()
    if len(content) > MAX_DOCUMENT_CHARS:
        raise HTTPException(status_code=413, detail="Document is larger than the configured limit.")
    document = Document(
        tenant_id=tenant_id,
        knowledge_base_id=kb.id,
        title=payload.title.strip(),
        source_name=payload.source_name.strip(),
        raw_text=content,
        status="processing",
        created_by=user.id,
    )
    db.add(document)
    db.commit()
    try:
        chunk_count = harness.index_document(db, document)
    except OllamaUnavailable as exc:
        document.status = "failed"
        document.error_message = "Ollama indexing failed; retry after checking model configuration."
        db.commit()
        raise HTTPException(status_code=503, detail=document.error_message) from exc
    audit(db, actor_id=user.id, tenant_id=tenant_id, action="document.indexed", resource_type="document", resource_id=str(document.id), details={"chunks": chunk_count})
    db.commit()
    return {"id": str(document.id), "title": document.title, "status": document.status, "chunks": chunk_count}


@app.post("/api/v1/tenants/{tenant_id}/knowledge-bases/{kb_id}/documents/{document_id}/reindex")
def reindex_document(
    tenant_id: uuid.UUID,
    kb_id: uuid.UUID,
    document_id: uuid.UUID,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    kb, membership = get_accessible_kb(db, user, tenant_id, kb_id)
    require_kb_writer(db, membership, kb)
    document = db.scalar(select(Document).where(
        Document.id == document_id,
        Document.tenant_id == tenant_id,
        Document.knowledge_base_id == kb.id,
    ))
    if not document:
        raise HTTPException(status_code=404, detail="Document not found.")
    document.status = "processing"
    document.error_message = ""
    db.commit()
    try:
        count = harness.index_document(db, document)
    except OllamaUnavailable as exc:
        document.status = "failed"
        document.error_message = "Ollama indexing failed."
        db.commit()
        raise HTTPException(status_code=503, detail=document.error_message) from exc
    return {"id": str(document.id), "status": document.status, "chunks": count}


@app.post("/api/v1/tenants/{tenant_id}/knowledge-bases/{kb_id}/ask")
def ask(
    tenant_id: uuid.UUID,
    kb_id: uuid.UUID,
    payload: AskInput,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    kb, _ = get_accessible_kb(db, user, tenant_id, kb_id)
    try:
        return harness.ask(db, kb, user.id, payload.question.strip())
    except OllamaUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/api/v1/tenants/{tenant_id}/knowledge-bases/{kb_id}/wiki/refresh")
def refresh_wiki(
    tenant_id: uuid.UUID,
    kb_id: uuid.UUID,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    kb, membership = get_accessible_kb(db, user, tenant_id, kb_id)
    require_kb_writer(db, membership, kb)
    try:
        result = harness.refresh_wiki(db, kb, user.id)
    except OllamaUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    audit(db, actor_id=user.id, tenant_id=tenant_id, action="wiki.refreshed", resource_type="knowledge_base", resource_id=str(kb.id), details=result)
    db.commit()
    return result


@app.post("/api/v1/tenants/{tenant_id}/knowledge-bases/{kb_id}/wiki/publish")
def publish_wiki(
    tenant_id: uuid.UUID,
    kb_id: uuid.UUID,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict[str, int]:
    kb, membership = get_accessible_kb(db, user, tenant_id, kb_id)
    require_kb_admin(membership, kb, db)
    entities = db.scalars(select(WikiEntity).where(WikiEntity.knowledge_base_id == kb.id)).all()
    for entity in entities:
        entity.is_published = True
    relations = db.scalars(select(WikiRelation).where(WikiRelation.knowledge_base_id == kb.id)).all()
    for relation in relations:
        relation.is_published = True
    audit(db, actor_id=user.id, tenant_id=tenant_id, action="wiki.published", resource_type="knowledge_base", resource_id=str(kb.id), details={"entities": len(entities), "relations": len(relations)})
    db.commit()
    return {"entities_published": len(entities), "relations_published": len(relations)}


@app.get("/api/v1/tenants/{tenant_id}/knowledge-bases/{kb_id}/wiki")
def get_wiki(
    tenant_id: uuid.UUID,
    kb_id: uuid.UUID,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    kb, membership = get_accessible_kb(db, user, tenant_id, kb_id)
    show_drafts = membership.role in {"tenant_admin", "unit_admin"}
    entity_query = select(WikiEntity).where(WikiEntity.knowledge_base_id == kb.id)
    relation_query = select(WikiRelation).where(WikiRelation.knowledge_base_id == kb.id)
    if not show_drafts:
        entity_query = entity_query.where(WikiEntity.is_published.is_(True))
        relation_query = relation_query.where(WikiRelation.is_published.is_(True))
    entities = db.scalars(entity_query.order_by(WikiEntity.name)).all()
    relations = db.scalars(relation_query).all()
    return {
        "nodes": [{
            "id": str(row.id),
            "name": row.name,
            "kind": row.kind,
            "summary": row.summary,
            "sources": row.sources,
            "status": "published" if row.is_published else "draft",
        } for row in entities],
        "edges": [{
            "source": str(row.source_entity_id),
            "target": str(row.target_entity_id),
            "label": row.label,
            "sources": row.sources,
            "status": "published" if row.is_published else "draft",
        } for row in relations],
    }


@app.get("/api/v1/tenants/{tenant_id}/harness/runs")
def list_harness_runs(
    tenant_id: uuid.UUID,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    membership = membership_for(db, user, tenant_id)
    if membership.role not in {"tenant_admin", "unit_admin"}:
        raise HTTPException(status_code=403, detail="Administrator role required.")
    query = select(HarnessRun).where(HarnessRun.tenant_id == tenant_id).order_by(HarnessRun.created_at.desc()).limit(100)
    if membership.role == "unit_admin":
        allowed_units = accessible_unit_ids(db, membership)
        allowed_kbs = select(KnowledgeBase.id).where(
            KnowledgeBase.tenant_id == tenant_id,
            ((KnowledgeBase.unit_id.is_(None)) | KnowledgeBase.unit_id.in_(allowed_units))
            if allowed_units else KnowledgeBase.unit_id.is_(None),
        )
        query = query.where(HarnessRun.knowledge_base_id.in_(allowed_kbs))
    rows = db.scalars(query).all()
    return [{
        "id": str(row.id),
        "knowledge_base_id": str(row.knowledge_base_id),
        "kind": row.kind,
        "model": row.model,
        "status": row.status,
        "latency_ms": row.latency_ms,
        "retrieved_chunks": row.retrieved_chunks,
        "citations": row.citations,
        "created_at": row.created_at.isoformat(),
    } for row in rows]
