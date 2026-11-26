from collections import deque
from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import KnowledgeBase, Membership, OrgUnit, User
from app.security import decode_access_token


bearer = HTTPBearer(auto_error=False)


def current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> User:
    if not credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Sign in required.")
    user_id = decode_access_token(credentials.credentials)
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token.")
    user = db.get(User, UUID(user_id))
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Account is unavailable.")
    return user


def membership_for(db: Session, user: User, tenant_id: UUID) -> Membership:
    membership = db.scalar(
        select(Membership).where(
            Membership.tenant_id == tenant_id,
            Membership.user_id == user.id,
            Membership.is_active.is_(True),
        )
    )
    if not membership:
        raise HTTPException(status_code=403, detail="You are not a member of this tenant.")
    return membership


def unit_tree_ids(db: Session, tenant_id: UUID, root_id: UUID) -> set[UUID]:
    rows = db.scalars(select(OrgUnit).where(OrgUnit.tenant_id == tenant_id)).all()
    children: dict[UUID | None, list[UUID]] = {}
    for row in rows:
        children.setdefault(row.parent_id, []).append(row.id)
    found: set[UUID] = set()
    queue = deque([root_id])
    while queue:
        unit_id = queue.popleft()
        if unit_id in found:
            continue
        found.add(unit_id)
        queue.extend(children.get(unit_id, []))
    return found


def require_tenant_admin(db: Session, user: User, tenant_id: UUID) -> Membership:
    membership = membership_for(db, user, tenant_id)
    if membership.role != "tenant_admin":
        raise HTTPException(status_code=403, detail="Tenant administrator role required.")
    return membership


def accessible_unit_ids(db: Session, membership: Membership) -> set[UUID]:
    if membership.role == "tenant_admin":
        return set(db.scalars(select(OrgUnit.id).where(OrgUnit.tenant_id == membership.tenant_id)).all())
    if membership.unit_id is None:
        return set()
    if membership.role == "unit_admin":
        return unit_tree_ids(db, membership.tenant_id, membership.unit_id)
    return {membership.unit_id}


def get_accessible_kb(
    db: Session,
    user: User,
    tenant_id: UUID,
    knowledge_base_id: UUID,
) -> tuple[KnowledgeBase, Membership]:
    membership = membership_for(db, user, tenant_id)
    kb = db.scalar(
        select(KnowledgeBase).where(
            KnowledgeBase.id == knowledge_base_id,
            KnowledgeBase.tenant_id == tenant_id,
        )
    )
    if not kb:
        raise HTTPException(status_code=404, detail="Knowledge base not found.")
    if kb.unit_id is not None and kb.unit_id not in accessible_unit_ids(db, membership):
        raise HTTPException(status_code=403, detail="This knowledge base is outside your organization scope.")
    return kb, membership


def require_kb_admin(membership: Membership, kb: KnowledgeBase, db: Session) -> None:
    if membership.role == "tenant_admin":
        return
    if membership.role == "unit_admin" and kb.unit_id is not None:
        if kb.unit_id in accessible_unit_ids(db, membership):
            return
    raise HTTPException(status_code=403, detail="Knowledge base administrator role required.")


def require_kb_writer(db: Session, membership: Membership, kb: KnowledgeBase) -> None:
    """Only tenant and in-scope unit administrators may change KB contents."""
    if membership.role == "tenant_admin":
        return
    if membership.role == "unit_admin" and kb.unit_id is not None:
        if kb.unit_id in accessible_unit_ids(db, membership):
            return
    raise HTTPException(status_code=403, detail="Knowledge base administrator role required.")
