import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from storage_lab.api import (
    add_platform_admin,
    current_user,
    list_platform_admins,
    list_projects,
    membership,
    remove_platform_admin,
)
from storage_lab.auth import Principal
from storage_lab.db import Base
from storage_lab.models import PlatformAdmin, PlatformAdminEvent, Project
from storage_lab.schemas import PlatformAdminCreate


def test_metadata_controls_global_access_and_admin_lifecycle():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    alice = Principal("https://idp.example/realms/platform", "alice")
    bob = Principal("https://idp.example/realms/platform", "bob")
    carol = Principal("https://idp.example/realms/platform", "carol")
    with Session(engine) as session:
        session.add(Project(id="a" * 32, name="Alpha", created_by=alice.identity))
        session.commit()
        assert current_user(alice, session) == {"platform_admin": False}
        assert list_projects(alice, session) == []
        with pytest.raises(HTTPException) as denied:
            add_platform_admin(PlatformAdminCreate(issuer=bob.issuer, subject=bob.subject), alice, session)
        assert denied.value.status_code == 403

        session.add(PlatformAdmin(identity=alice.identity, granted_by="bootstrap"))
        session.commit()
        assert current_user(alice, session) == {"platform_admin": True}
        assert list_projects(alice, session)[0].role == "admin"
        assert membership(session, "a" * 32, alice, admin=True).role == "admin"

        add_platform_admin(PlatformAdminCreate(issuer=bob.issuer, subject=bob.subject), alice, session)
        assert len(list_platform_admins(alice, session)) == 2
        assert current_user(bob, session) == {"platform_admin": True}
        remove_platform_admin(PlatformAdminCreate(issuer=bob.issuer, subject=bob.subject), alice, session)
        assert current_user(bob, session) == {"platform_admin": False}
        with pytest.raises(HTTPException) as last_admin:
            remove_platform_admin(PlatformAdminCreate(issuer=alice.issuer, subject=alice.subject), alice, session)
        assert last_admin.value.status_code == 409
        with pytest.raises(HTTPException) as denied_again:
            list_platform_admins(carol, session)
        assert denied_again.value.status_code == 403
        assert [event.action for event in session.scalars(select(PlatformAdminEvent).order_by(PlatformAdminEvent.id))] == ["grant", "revoke"]
    engine.dispose()
