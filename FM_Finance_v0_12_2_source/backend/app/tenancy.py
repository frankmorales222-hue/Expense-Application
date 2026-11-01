"""Company isolation enforced at the database-session level.

Every request resolves one current company (see app.security) and stores it in
``session.info["company_id"]``. Then, for that session:

* every ORM SELECT (including ``session.get``, joins, subqueries and eager loads) on a
  company-scoped model is filtered to that company, so another company's rows can't be read
  even if a route forgets its own filter;
* every new company-scoped row is stamped with that company before it is written, and a row
  that already belongs to a different company can't be written through this session.

Sessions without a company (startup, migrations, sign-in, platform administration) are not
filtered; code running there must set ``company_id`` explicitly.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import event
from sqlalchemy.orm import ORMExecuteState, Session, with_loader_criteria

from .models import AuditLog, CompanyScoped

KEY = "company_id"
# Used when a signed-in user has no company: scoped reads return nothing (fail closed).
NO_COMPANY = uuid.UUID(int=0)


class CompanyMismatch(RuntimeError):
    pass


def set_company(session: Session, company_id: uuid.UUID | None) -> None:
    if company_id is None:
        session.info.pop(KEY, None)
    else:
        session.info[KEY] = company_id


def company_of(session: Session) -> uuid.UUID | None:
    return session.info.get(KEY)


@contextmanager
def acting_as(session: Session, company_id: uuid.UUID) -> Iterator[None]:
    """Temporarily work in another company (e.g. seeding a company that was just created).
    Pending changes are flushed under the right company on the way in and out."""
    previous = session.info.get(KEY)
    session.flush()
    set_company(session, company_id)
    try:
        yield
        session.flush()
    finally:
        set_company(session, previous)


@event.listens_for(Session, "do_orm_execute")
def _filter_reads(state: ORMExecuteState) -> None:
    company_id = state.session.info.get(KEY)
    if company_id is None or not state.is_select:
        return
    state.statement = state.statement.options(
        with_loader_criteria(CompanyScoped, lambda cls: cls.company_id == company_id,
                             include_aliases=True, track_closure_variables=True)
    )


@event.listens_for(Session, "before_flush")
def _stamp_writes(session: Session, flush_context, instances) -> None:
    company_id = session.info.get(KEY)
    for obj in list(session.new) + list(session.dirty):
        if not isinstance(obj, CompanyScoped):
            continue
        if obj.company_id is None:
            if company_id is None or company_id == NO_COMPANY:
                if isinstance(obj, AuditLog):
                    continue  # account-level event
                raise CompanyMismatch(f"{type(obj).__name__} has no company")
            obj.company_id = company_id
        elif company_id is not None and obj.company_id != company_id:
            raise CompanyMismatch(f"{type(obj).__name__} belongs to another company")
