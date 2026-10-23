"""End-to-end smoke test exercising every endpoint over an in-memory SQLite DB.

Run with: python -m pytest tests/ -q   (or plainly: python tests/test_smoke.py)
"""
import io
import uuid

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import Article, CommodityGroup, RequestActivity, Supplier
from app.seed import seed

# ---------------------------------------------------------------------------
# Test database (in-memory SQLite) + commodity group seed
# ---------------------------------------------------------------------------
engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)


# SQLite ignores foreign keys (and their ON DELETE CASCADE) unless enabled —
# Postgres enforces them natively.
from sqlalchemy import event  # noqa: E402


@event.listens_for(engine, "connect")
def _enable_sqlite_fks(dbapi_connection, _record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()
TestingSession = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

Base.metadata.create_all(engine)

# Seed reference data through the same code path production uses, so the test DB
# mirrors it (large commodity taxonomy + 120 suppliers with empty descriptions).
with TestingSession() as _s:
    seed(_s)


def _override_get_db():
    db = TestingSession()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = _override_get_db
client = TestClient(app)


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_full_user_journey():
    # --- health ---
    assert client.get("/health").json() == {"status": "ok"}

    # --- unauthenticated access is rejected ---
    assert client.get("/requests").status_code == 401
    assert client.get("/auth/me").status_code == 401
    assert client.get("/commodity-groups").status_code == 401

    # --- signup ---
    r = client.post(
        "/auth/signup",
        json={"email": "Owner@Example.com", "password": "secret123", "full_name": "Olive Owner"},
    )
    assert r.status_code == 201, r.text
    owner_token = r.json()["access_token"]
    assert r.json()["user"]["email"] == "owner@example.com"  # lower-cased

    # duplicate signup -> 409
    r = client.post(
        "/auth/signup", json={"email": "owner@example.com", "password": "secret123"}
    )
    assert r.status_code == 409

    # short password -> 422
    r = client.post("/auth/signup", json={"email": "x@example.com", "password": "abc"})
    assert r.status_code == 422

    # --- signin ---
    assert (
        client.post(
            "/auth/signin", json={"email": "owner@example.com", "password": "wrong"}
        ).status_code
        == 401
    )
    r = client.post(
        "/auth/signin", json={"email": "owner@example.com", "password": "secret123"}
    )
    assert r.status_code == 200
    owner_token = r.json()["access_token"]

    # --- me ---
    r = client.get("/auth/me", headers=_auth(owner_token))
    assert r.status_code == 200
    assert r.json()["profile"]["full_name"] == "Olive Owner"

    # --- no organization yet: org-scoped endpoints -> 403 ---
    assert client.get("/requests", headers=_auth(owner_token)).status_code == 403
    assert client.get("/organizations/me", headers=_auth(owner_token)).status_code == 403

    # --- create organization ---
    r = client.post(
        "/organizations",
        json={"name": "Acme Corp", "slug": "acme-corp"},
        headers=_auth(owner_token),
    )
    assert r.status_code == 201, r.text
    assert r.json()["role"] == "admin"

    # duplicate slug -> 409
    r = client.post(
        "/organizations",
        json={"name": "Acme 2", "slug": "acme-corp"},
        headers=_auth(owner_token),
    )
    assert r.status_code == 409

    # --- organizations/me ---
    r = client.get("/organizations/me", headers=_auth(owner_token))
    assert r.status_code == 200
    assert r.json()["name"] == "Acme Corp"
    assert r.json()["role"] == "admin"

    # --- commodity groups ---
    r = client.get("/commodity-groups", headers=_auth(owner_token))
    assert r.status_code == 200
    group_ids = [g["id"] for g in r.json()]
    assert 15 in group_ids and 31 in group_ids and 43 in group_ids
    assert len(group_ids) >= 300

    # --- create request (camelCase payload, as the frontend sends) ---
    payload = {
        "requestorName": "Olive Owner",
        "titleShortDescription": "Software Licenses",
        "vendorName": "Adobe Systems",
        "vatId": "12-3456789",
        "commodityGroupId": 31,
        "totalCost": 1500.0,
        "department": "IT",
        "orderLines": [
            {
                "positionDescription": "Creative Cloud",
                "unitPrice": 150.0,
                "amount": 10,
                "unit": "licenses",
                "totalPrice": 1500.0,
            }
        ],
    }
    r = client.post("/requests", json=payload, headers=_auth(owner_token))
    assert r.status_code == 201, r.text
    request_id = r.json()["id"]
    assert r.json()["status"] == "open"
    assert r.json()["requestor_name"] == "Olive Owner"
    assert r.json()["commodity_groups"]["name"] == "Software"
    assert len(r.json()["order_lines"]) == 1
    assert r.json()["order_lines"][0]["position_description"] == "Creative Cloud"

    # unknown commodity group -> 422
    bad = dict(payload, commodityGroupId=999999)
    assert client.post("/requests", json=bad, headers=_auth(owner_token)).status_code == 422

    # --- list requests ---
    r = client.get("/requests", headers=_auth(owner_token))
    assert r.status_code == 200
    assert len(r.json()) == 1

    # --- status update logs activity ---
    r = client.patch(
        f"/requests/{request_id}/status",
        json={"status": "in_progress"},
        headers=_auth(owner_token),
    )
    assert r.status_code == 200
    assert r.json()["status"] == "in_progress"

    def _activity_actions() -> list[str]:
        with TestingSession() as s:
            rows = s.scalars(
                select(RequestActivity)
                .where(RequestActivity.request_id == uuid.UUID(request_id))
                .order_by(RequestActivity.created_at)
            ).all()
            return [a.action for a in rows]

    # created + status_changed so far
    assert _activity_actions() == ["created", "status_changed"]

    # same-status update does NOT add activity
    client.patch(
        f"/requests/{request_id}/status",
        json={"status": "in_progress"},
        headers=_auth(owner_token),
    )
    assert _activity_actions() == ["created", "status_changed"]

    # invalid status -> 422
    r = client.patch(
        f"/requests/{request_id}/status",
        json={"status": "bogus"},
        headers=_auth(owner_token),
    )
    assert r.status_code == 422

    # --- full update replaces order lines ---
    update = {
        "requestorName": "Olive Owner",
        "title": "Software Licenses (updated)",
        "vendorName": "Adobe Systems",
        "vatId": "12-3456789",
        "commodityGroupId": 15,
        "totalCost": 500.0,
        "department": "IT",
        "orderLines": [
            {
                "positionDescription": "Desk",
                "unitPrice": 250.0,
                "amount": 2,
                "unit": "pieces",
                "totalPrice": 500.0,
            },
            {
                "positionDescription": "Chair",
                "unitPrice": 0.0,
                "amount": 1.28,
                "unit": "meters",
                "totalPrice": 0.0,
            },
        ],
    }
    r = client.put(f"/requests/{request_id}", json=update, headers=_auth(owner_token))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["title"] == "Software Licenses (updated)"
    assert body["commodity_groups"]["id"] == 15
    assert [l["position_description"] for l in body["order_lines"]] == ["Desk", "Chair"]
    assert body["order_lines"][1]["amount"] == 1.28  # decimal amounts supported
    assert [l["line_order"] for l in body["order_lines"]] == [1, 2]

    # --- invites ---
    r = client.post(
        "/organizations/me/invites",
        json={"email": "member@example.com"},
        headers=_auth(owner_token),
    )
    assert r.status_code == 201, r.text
    invite_token = None
    # token isn't exposed via the API response; fetch from DB like the email link would carry it
    from app.models import OrganizationInvite

    with TestingSession() as s:
        invite = s.scalar(
            select(OrganizationInvite).where(OrganizationInvite.email == "member@example.com")
        )
        assert invite is not None and invite.token and invite.expires_at is not None
        invite_token = invite.token

    # duplicate invite -> 409
    r = client.post(
        "/organizations/me/invites",
        json={"email": "member@example.com"},
        headers=_auth(owner_token),
    )
    assert r.status_code == 409

    # members endpoint shows 1 member + 1 pending invite
    r = client.get("/organizations/me/members", headers=_auth(owner_token))
    assert r.status_code == 200
    assert len(r.json()["members"]) == 1
    assert r.json()["members"][0]["profiles"]["full_name"] == "Olive Owner"
    assert len(r.json()["invites"]) == 1

    # --- second user accepts invite ---
    r = client.post(
        "/auth/signup",
        json={"email": "member@example.com", "password": "secret123", "full_name": "Mia Member"},
    )
    member_token = r.json()["access_token"]

    # wrong-email user cannot accept
    r = client.post(
        "/auth/signup", json={"email": "other@example.com", "password": "secret123"}
    )
    other_token = r.json()["access_token"]
    r = client.post(
        "/organizations/invites/accept",
        json={"token": invite_token},
        headers=_auth(other_token),
    )
    assert r.status_code == 403

    r = client.post(
        "/organizations/invites/accept",
        json={"token": invite_token},
        headers=_auth(member_token),
    )
    assert r.status_code == 200, r.text
    assert r.json()["role"] == "requester"

    # accepted invite cannot be reused
    r = client.post(
        "/organizations/invites/accept",
        json={"token": invite_token},
        headers=_auth(member_token),
    )
    assert r.status_code == 404

    # member sees the org's requests
    r = client.get("/requests", headers=_auth(member_token))
    assert r.status_code == 200
    assert len(r.json()) == 1

    # members endpoint now shows 2 members, 0 pending invites
    r = client.get("/organizations/me/members", headers=_auth(owner_token))
    assert len(r.json()["members"]) == 2
    assert len(r.json()["invites"]) == 0

    # plain member cannot invite (admin required)
    r = client.post(
        "/organizations/me/invites",
        json={"email": "third@example.com"},
        headers=_auth(member_token),
    )
    assert r.status_code == 403

    # --- cancel invite ---
    r = client.post(
        "/organizations/me/invites",
        json={"email": "third@example.com"},
        headers=_auth(owner_token),
    )
    invite_id = r.json()["id"]
    r = client.delete(
        f"/organizations/me/invites/{invite_id}", headers=_auth(owner_token)
    )
    assert r.status_code == 204

    # --- isolation: user in a different org sees nothing ---
    r = client.post(
        "/organizations",
        json={"name": "Other Org", "slug": "other-org"},
        headers=_auth(other_token),
    )
    assert r.status_code == 201
    r = client.get("/requests", headers=_auth(other_token))
    assert r.json() == []
    # ...and cannot touch the first org's request
    assert (
        client.delete(f"/requests/{request_id}", headers=_auth(other_token)).status_code
        == 404
    )

    # --- delete request ---
    r = client.delete(f"/requests/{request_id}", headers=_auth(owner_token))
    assert r.status_code == 204
    assert client.get("/requests", headers=_auth(owner_token)).json() == []
    # order lines + activity cascaded
    with TestingSession() as s:
        assert (
            s.scalars(
                select(RequestActivity).where(
                    RequestActivity.request_id == uuid.UUID(request_id)
                )
            ).all()
            == []
        )


def test_pdf_parse():
    # Build a tiny real PDF in memory, then round-trip it through the endpoint.
    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    buf = io.BytesIO()
    writer.write(buf)

    r = client.post("/auth/signup", json={"email": "pdf@example.com", "password": "secret123"})
    token = r.json()["access_token"]

    r = client.post(
        "/pdf/parse",
        files={"file": ("offer.pdf", buf.getvalue(), "application/pdf")},
        headers=_auth(token),
    )
    assert r.status_code == 200, r.text
    assert "text" in r.json()  # blank page -> empty text, but parses fine

    # Upper-case extension and a generic browser-reported type are still a PDF.
    r = client.post(
        "/pdf/parse",
        files={"file": ("QuoteA0492_23.Pdf", buf.getvalue(), "application/octet-stream")},
        headers=_auth(token),
    )
    assert r.status_code == 200, r.text

    # A file that claims to be a PDF but isn't one is rejected.
    r = client.post(
        "/pdf/parse",
        files={"file": ("fake.pdf", b"not a pdf", "application/pdf")},
        headers=_auth(token),
    )
    assert r.status_code == 400

    # non-PDF rejected
    r = client.post(
        "/pdf/parse",
        files={"file": ("notes.txt", b"hello", "text/plain")},
        headers=_auth(token),
    )
    assert r.status_code == 400


def test_activity_log_and_document():
    from pypdf import PdfWriter

    admin = client.post(
        "/auth/signin", json={"email": "admin@acme.com", "password": "demo1234"}
    ).json()["access_token"]

    payload = {
        "requestorName": "Alex Admin", "titleShortDescription": "Chairs",
        "vendorName": "FurnitureCo", "vatId": "12-0000001", "commodityGroupId": 15,
        "totalCost": 500.0, "department": "Ops",
        "orderLines": [
            {"positionDescription": "Chair", "unitPrice": 250, "amount": 2, "unit": "pc", "totalPrice": 500}
        ],
    }
    rid = client.post("/requests", json=payload, headers=_auth(admin)).json()["id"]

    # edit two fields -> one 'updated' activity naming those fields
    updated = dict(payload)
    updated["title"] = "Office Chairs"
    updated["totalCost"] = 600.0
    updated["orderLines"] = [
        {"positionDescription": "Chair", "unitPrice": 300, "amount": 2, "unit": "pc", "totalPrice": 600}
    ]
    # RequestUpdate uses "title" (not titleShortDescription)
    updated = {
        "requestorName": "Alex Admin", "title": "Office Chairs", "vendorName": "FurnitureCo",
        "vatId": "12-0000001", "commodityGroupId": 15, "totalCost": 600.0, "department": "Ops",
        "orderLines": updated["orderLines"],
    }
    r = client.put(f"/requests/{rid}", json=updated, headers=_auth(admin))
    assert r.status_code == 200, r.text

    # approve, then a status change
    client.patch(f"/requests/{rid}/approval", json={"decision": "approved"}, headers=_auth(admin))
    client.patch(f"/requests/{rid}/status", json={"status": "closed"}, headers=_auth(admin))

    # attach a PDF
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    buf = io.BytesIO()
    writer.write(buf)
    r = client.put(
        f"/requests/{rid}/document",
        files={"file": ("offer.pdf", buf.getvalue(), "application/pdf")},
        headers=_auth(admin),
    )
    assert r.status_code == 204, r.text

    # activity feed (newest first) captures every event
    r = client.get(f"/requests/{rid}/activity", headers=_auth(admin))
    assert r.status_code == 200
    actions = [a["action"] for a in r.json()]
    assert set(actions) == {
        "created", "updated", "approved", "status_changed", "document_attached"
    }
    updated_entry = next(a for a in r.json() if a["action"] == "updated")
    assert set(updated_entry["detail"]["changed_fields"]) == {
        "title", "total_cost", "order_lines"
    }

    # the stored PDF is served back
    r = client.get(f"/requests/{rid}/document", headers=_auth(admin))
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/pdf"
    assert r.content[:4] == b"%PDF"

    client.delete(f"/requests/{rid}", headers=_auth(admin))


def test_extraction_without_api_key(monkeypatch):
    # Changed for spec 001: extraction needs the caller's organization (to know
    # who the buyer is), and failures carry a plain-language message plus an
    # errorCode instead of technical text such as the env var name (FR-005).
    monkeypatch.setattr("app.services.extraction.settings.openai_api_key", None)
    r = client.post("/auth/signin", json={"email": "requester@acme.com", "password": "demo1234"})
    token = r.json()["access_token"]

    r = client.post("/extraction", json={"text": "Quote No. 123"}, headers=_auth(token))
    assert r.status_code == 200
    body = r.json()
    # Without OPENAI_API_KEY configured the endpoint reports a clean failure
    # envelope rather than an HTTP error.
    assert body["success"] is False
    assert body["errorCode"] == "not_configured"
    assert "OPENAI" not in body["error"]

    # empty text
    r = client.post("/extraction", json={"text": "  "}, headers=_auth(token))
    assert r.json()["success"] is False
    assert r.json()["errorCode"] == "unreadable"

    # A user without an organization cannot extract.
    r = client.post("/auth/signup", json={"email": "ex@example.com", "password": "secret123"})
    r = client.post(
        "/extraction", json={"text": "Quote"}, headers=_auth(r.json()["access_token"])
    )
    assert r.status_code == 403


def test_extraction_uses_buyer_names_and_profile_department(monkeypatch):
    from app.models import Profile, User
    from app.routers import extraction as extraction_router
    from app.schemas.extraction import ExtractionResponse

    captured = {}

    def fake_extract(text, db, **kwargs):
        captured.update(kwargs)
        return ExtractionResponse(success=False, error_code="unreadable", error="x")

    monkeypatch.setattr(extraction_router, "extract_vendor_data", fake_extract)
    with TestingSession() as db:
        user = db.scalar(select(User).where(User.email == "buyer@acme.com"))
        db.get(Profile, user.id).department = "Facilities"
        db.commit()

    token = client.post(
        "/auth/signin", json={"email": "buyer@acme.com", "password": "demo1234"}
    ).json()["access_token"]
    assert client.post("/extraction", json={"text": "Q"}, headers=_auth(token)).status_code == 200
    # Org name + seeded aliases; department is the requester's own, not the quote's.
    assert captured["buyer_names"] == [
        "Acme Corp", "ACME Corp", "Lio Technologies, Inc.", "askLio"
    ]
    assert captured["department"] == "Facilities"


def test_commodity_groups_expanded():
    r = client.post("/auth/signup", json={"email": "cg@example.com", "password": "secret123"})
    token = r.json()["access_token"]

    r = client.get("/commodity-groups", headers=_auth(token))
    assert r.status_code == 200
    groups = r.json()
    # Large taxonomy.
    assert len(groups) >= 1000, f"expected a large taxonomy, got {len(groups)}"
    # ids contiguous from 1; first one matches the original taxonomy
    assert groups[0] == {"id": 1, "category": "General Services", "name": "Accommodation Rentals"}
    assert len({g["category"] for g in groups}) >= 20

    # Every leaf name belongs to exactly one category.
    by_name: dict[str, set[str]] = {}
    for g in groups:
        by_name.setdefault(g["name"], set()).add(g["category"])
    ambiguous = {n: c for n, c in by_name.items() if len(c) > 1}
    assert not ambiguous, f"names spanning multiple categories: {ambiguous}"


def _signin(email: str, password: str = "demo1234") -> str:
    r = client.post("/auth/signin", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def test_suppliers_are_org_scoped_master_data():
    token = _signin("admin@acme.com")

    # auth required
    assert client.get("/suppliers").status_code == 401

    r = client.get("/suppliers/count", headers=_auth(token))
    assert r.status_code == 200
    assert r.json()["count"] >= 100

    r = client.get("/suppliers?limit=500", headers=_auth(token))
    assert r.status_code == 200
    suppliers = r.json()
    assert len(suppliers) >= 100
    # every seeded supplier has an empty description, ready for enrichment
    assert all((s["description"] or "") == "" for s in suppliers)
    # sorted by name, carries catalog metadata
    assert suppliers == sorted(suppliers, key=lambda s: s["name"])
    assert all(s["name"] and s["category"] for s in suppliers)

    # search filter works
    r = client.get("/suppliers?search=freight", headers=_auth(token))
    assert r.status_code == 200
    assert len(r.json()) >= 1
    assert all("freight" in s["name"].lower() for s in r.json())

    # master data is private to Acme: another tenant sees none of it
    other = _signin("admin@walmart.com")
    assert client.get("/suppliers/count", headers=_auth(other)).json()["count"] == 0
    assert client.get("/suppliers?limit=500", headers=_auth(other)).json() == []


def test_articles_catalog_paginated_and_searchable():
    token = _signin("admin@acme.com")

    # auth required
    assert client.get("/articles").status_code == 401

    r = client.get("/articles/count", headers=_auth(token))
    assert r.status_code == 200
    total = r.json()["count"]
    assert total >= 1000

    # first page: bounded size, correct envelope, ordered by article number
    r = client.get("/articles?limit=25&offset=0", headers=_auth(token))
    assert r.status_code == 200
    page = r.json()
    assert page["total"] == total
    assert page["limit"] == 25 and page["offset"] == 0
    assert len(page["items"]) == 25
    numbers = [a["article_number"] for a in page["items"]]
    assert numbers == sorted(numbers)
    # every article carries its supplier and a price
    assert all(a["supplier_id"] and a["supplier_name"] for a in page["items"])
    assert all(a["description"] and a["unit"] for a in page["items"])

    # second page returns different rows
    r2 = client.get("/articles?limit=25&offset=25", headers=_auth(token))
    assert r2.status_code == 200
    assert {a["id"] for a in r2.json()["items"]}.isdisjoint({a["id"] for a in page["items"]})

    # search matches the seeded office-decoration items
    r = client.get("/articles?search=moss", headers=_auth(token))
    assert r.status_code == 200
    found = r.json()
    assert found["total"] >= 1
    assert any("moss wall" in a["description"].lower() for a in found["items"])

    # catalog is private to Acme: another tenant's catalog is empty
    other = _signin("admin@walmart.com")
    assert client.get("/articles/count", headers=_auth(other)).json()["count"] == 0
    assert client.get("/articles", headers=_auth(other)).json()["total"] == 0


def test_seed_is_idempotent():
    # The DB was already seeded at import; seeding again must add nothing and
    # must not change the row counts (safe to run on every startup).
    with TestingSession() as db:
        before_cg = db.scalar(select(func.count()).select_from(CommodityGroup))
        before_sup = db.scalar(select(func.count()).select_from(Supplier))
        before_art = db.scalar(select(func.count()).select_from(Article))
        counts = seed(db)
        after_cg = db.scalar(select(func.count()).select_from(CommodityGroup))
        after_sup = db.scalar(select(func.count()).select_from(Supplier))
        after_art = db.scalar(select(func.count()).select_from(Article))

    assert all(v == 0 for v in counts.values()), counts
    assert before_cg == after_cg
    assert before_sup == after_sup
    assert before_art == after_art


def test_demo_user_can_sign_in():
    # The seeded demo account works out of the box (documented in the README).
    r = client.post(
        "/auth/signin", json={"email": "admin@acme.com", "password": "demo1234"}
    )
    assert r.status_code == 200, r.text
    token = r.json()["access_token"]

    # ...and already belongs to an organization, so the app is usable immediately.
    r = client.get("/organizations/me", headers=_auth(token))
    assert r.status_code == 200
    assert r.json()["slug"] == "acme"
    assert r.json()["role"] == "admin"

    assert client.get("/requests", headers=_auth(token)).status_code == 200


def test_approval_flow_with_roles():
    # Uses the seeded demo org: requester creates, buyer approves.
    def signin(email: str) -> str:
        r = client.post("/auth/signin", json={"email": email, "password": "demo1234"})
        assert r.status_code == 200, r.text
        return r.json()["access_token"]

    requester = signin("requester@acme.com")
    buyer = signin("buyer@acme.com")
    admin = signin("admin@acme.com")

    payload = {
        "requestorName": "Rene Requester",
        "titleShortDescription": "Laptops",
        "vendorName": "TechSupply",
        "vatId": "99-9999999",
        "commodityGroupId": 31,
        "totalCost": 4200.0,
        "department": "Engineering",
        "orderLines": [
            {"positionDescription": "Laptop", "unitPrice": 1400, "amount": 3, "unit": "pc", "totalPrice": 4200}
        ],
    }
    r = client.post("/requests", json=payload, headers=_auth(requester))
    assert r.status_code == 201, r.text
    request_id = r.json()["id"]
    # every new request starts pending
    assert r.json()["approval_status"] == "pending"
    assert r.json()["approved_by"] is None

    # requester cannot approve (not a buyer/admin)
    r = client.patch(
        f"/requests/{request_id}/approval",
        json={"decision": "approved"},
        headers=_auth(requester),
    )
    assert r.status_code == 403

    # buyer approves
    r = client.patch(
        f"/requests/{request_id}/approval",
        json={"decision": "approved"},
        headers=_auth(buyer),
    )
    assert r.status_code == 200, r.text
    assert r.json()["approval_status"] == "approved"
    assert r.json()["approved_by"] is not None
    assert r.json()["approved_at"] is not None

    # already decided -> 409 (even for an admin)
    r = client.patch(
        f"/requests/{request_id}/approval",
        json={"decision": "rejected"},
        headers=_auth(admin),
    )
    assert r.status_code == 409

    # admins can also decide; rejection works
    r = client.post("/requests", json=payload, headers=_auth(requester))
    second_id = r.json()["id"]
    r = client.patch(
        f"/requests/{second_id}/approval",
        json={"decision": "rejected"},
        headers=_auth(admin),
    )
    assert r.status_code == 200
    assert r.json()["approval_status"] == "rejected"

    # buyers cannot touch org settings (admin-only)
    assert (
        client.patch(
            "/organizations/me/settings",
            json={"required_fields": []},
            headers=_auth(buyer),
        ).status_code
        == 403
    )

    # cleanup: remove the demo-org requests this test created
    for rid in (request_id, second_id):
        client.delete(f"/requests/{rid}", headers=_auth(admin))


def test_org_settings_required_fields():
    # Fresh org (settings default to empty).
    r = client.post(
        "/auth/signup", json={"email": "settings@example.com", "password": "secret123"}
    )
    token = r.json()["access_token"]
    client.post(
        "/organizations",
        json={"name": "Settings Co", "slug": "settings-co"},
        headers=_auth(token),
    )

    # Default settings: nothing extra required. (Changed for spec 001: settings
    # now also include the empty buyer_aliases list.)
    r = client.get("/organizations/me/settings", headers=_auth(token))
    assert r.status_code == 200
    assert r.json() == {"required_fields": [], "buyer_aliases": []}

    base_payload = {
        "requestorName": "S", "titleShortDescription": "T", "vendorName": "V",
        "vatId": "", "commodityGroupId": 31, "totalCost": 10.0, "department": "",
        "orderLines": [
            {"positionDescription": "x", "unitPrice": 10, "amount": 1, "unit": "pc", "totalPrice": 10}
        ],
    }
    # Without a requirement, a request with blank vat_id/department is accepted.
    assert client.post("/requests", json=base_payload, headers=_auth(token)).status_code == 201

    # Configure vat_id + department as required.
    r = client.patch(
        "/organizations/me/settings",
        json={"required_fields": ["vat_id", "department"]},
        headers=_auth(token),
    )
    assert r.status_code == 200
    assert set(r.json()["required_fields"]) == {"vat_id", "department"}

    # Now the same blank-field request is rejected...
    r = client.post("/requests", json=base_payload, headers=_auth(token))
    assert r.status_code == 422
    assert "vat_id" in r.json()["detail"] and "department" in r.json()["detail"]

    # ...and providing them succeeds.
    ok = dict(base_payload, vatId="12-3000123", department="IT")
    assert client.post("/requests", json=ok, headers=_auth(token)).status_code == 201

    # Unknown setting keys are rejected (validated at the edge).
    assert (
        client.patch(
            "/organizations/me/settings",
            json={"bogus": True},
            headers=_auth(token),
        ).status_code
        == 422
    )


def test_org_settings_admin_only():
    # A plain member cannot change settings.
    owner = client.post(
        "/auth/signup", json={"email": "so-owner@example.com", "password": "secret123"}
    ).json()["access_token"]
    client.post(
        "/organizations",
        json={"name": "SO Co", "slug": "so-co"},
        headers=_auth(owner),
    )
    invite = client.post(
        "/organizations/me/invites",
        json={"email": "so-member@example.com"},
        headers=_auth(owner),
    )
    from app.models import OrganizationInvite

    with TestingSession() as db:
        token_val = db.scalar(
            select(OrganizationInvite.token).where(
                OrganizationInvite.email == "so-member@example.com"
            )
        )
    member = client.post(
        "/auth/signup", json={"email": "so-member@example.com", "password": "secret123"}
    ).json()["access_token"]
    client.post(
        "/organizations/invites/accept", json={"token": token_val}, headers=_auth(member)
    )

    # member can read settings but not change them
    assert client.get("/organizations/me/settings", headers=_auth(member)).status_code == 200
    r = client.patch(
        "/organizations/me/settings",
        json={"required_fields": ["vat_id"]},
        headers=_auth(member),
    )
    assert r.status_code == 403


def test_org_settings_merge_and_buyer_aliases():
    token = client.post(
        "/auth/signup", json={"email": "alias-admin@example.com", "password": "secret123"}
    ).json()["access_token"]
    client.post(
        "/organizations", json={"name": "Alias Co", "slug": "alias-co"}, headers=_auth(token)
    )

    r = client.patch(
        "/organizations/me/settings",
        json={"buyer_aliases": [" Alias Company, Inc. ", "alias company, inc.", "AliasCo"]},
        headers=_auth(token),
    )
    assert r.status_code == 200, r.text
    # Trimmed and de-duplicated (case-insensitive).
    assert r.json()["buyer_aliases"] == ["Alias Company, Inc.", "AliasCo"]

    # Saving another setting keeps the aliases (FR-010), and vice versa.
    r = client.patch(
        "/organizations/me/settings", json={"required_fields": ["vat_id"]}, headers=_auth(token)
    )
    assert r.json() == {
        "required_fields": ["vat_id"], "buyer_aliases": ["Alias Company, Inc.", "AliasCo"]
    }
    r = client.patch(
        "/organizations/me/settings", json={"buyer_aliases": []}, headers=_auth(token)
    )
    assert r.json() == {"required_fields": ["vat_id"], "buyer_aliases": []}

    for bad in ([""], ["x" * 121], [f"name {i}" for i in range(21)]):
        r = client.patch(
            "/organizations/me/settings", json={"buyer_aliases": bad}, headers=_auth(token)
        )
        assert r.status_code == 422, bad

    # Seeded tenant: Acme starts with its aliases; buyers can read but not edit.
    buyer = client.post(
        "/auth/signin", json={"email": "buyer@acme.com", "password": "demo1234"}
    ).json()["access_token"]
    r = client.get("/organizations/me/settings", headers=_auth(buyer))
    assert "Lio Technologies, Inc." in r.json()["buyer_aliases"]
    r = client.patch(
        "/organizations/me/settings", json={"buyer_aliases": []}, headers=_auth(buyer)
    )
    assert r.status_code == 403


def test_request_keeps_quote_details_and_discounts():
    token = client.post(
        "/auth/signin", json={"email": "requester@acme.com", "password": "demo1234"}
    ).json()["access_token"]
    line = {
        "positionDescription": "Moss Art Panel", "unitPrice": 894.08, "amount": 1,
        "unit": "pieces", "discountPercent": 20, "totalPrice": 715.26,
    }
    payload = {
        "requestorName": "R", "titleShortDescription": "Moss", "vendorName": "Greenmantle",
        "vatId": "85-3252405", "commodityGroupId": 15, "totalCost": 1686.14,
        "department": "", "orderLines": [line],
        "quoteNumber": "4120", "quoteDate": "2023-11-28", "validUntil": "2024-01-27",
        "currency": "usd", "netTotal": 1337.26, "shippingAmount": 215,
        "taxAmount": 133.88, "feesAmount": None,
    }
    r = client.post("/requests", json=payload, headers=_auth(token))
    assert r.status_code == 201, r.text
    created = r.json()
    assert created["quote_number"] == "4120"
    assert created["quote_date"] == "2023-11-28"
    assert created["quote_valid_until"] == "2024-01-27"
    assert created["currency"] == "USD"
    assert (created["net_total"], created["shipping_amount"], created["tax_amount"]) == (
        1337.26, 215, 133.88
    )
    assert created["order_lines"][0]["discount_percent"] == 20

    # The detail-page edit form doesn't send quote details: they must survive.
    edit = {
        "requestorName": "R", "title": "Moss panel", "vendorName": "Greenmantle",
        "vatId": "85-3252405", "commodityGroupId": 15, "totalCost": 1686.14,
        "department": "", "orderLines": [line],
    }
    r = client.put(f"/requests/{created['id']}", json=edit, headers=_auth(token))
    assert r.status_code == 200, r.text
    assert r.json()["quote_number"] == "4120"
    assert r.json()["order_lines"][0]["discount_percent"] == 20

    # Sent explicitly, they change and the edit is logged.
    r = client.put(
        f"/requests/{created['id']}", json=dict(edit, quoteNumber="4120-B"), headers=_auth(token)
    )
    assert r.json()["quote_number"] == "4120-B"
    activity = client.get(f"/requests/{created['id']}/activity", headers=_auth(token)).json()
    # (SQLite timestamps share a second here, so don't rely on ordering.)
    assert any(a["summary"] == "Updated quote number" for a in activity)

    # Discounts are validated.
    bad = dict(payload, orderLines=[dict(line, discountPercent=150)])
    assert client.post("/requests", json=bad, headers=_auth(token)).status_code == 422


def _signin(email: str) -> str:
    r = client.post("/auth/signin", json={"email": email, "password": "demo1234"})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def test_catalog_suggestions_api_and_tenant_isolation():
    toner = {"key": "0", "description": "Toner cartridge cyan", "unit": "pieces", "quantity": 5}
    r = client.post(
        "/catalog/suggestions", json={"lines": [toner]}, headers=_auth(_signin("requester@acme.com"))
    )
    assert r.status_code == 200, r.text
    body = r.json()
    # No AI key in tests: exact-token fallback, still from Acme's catalog only.
    assert body["source"] == "lexical"
    assert [s["articleNumber"] for s in body["lines"][0]["suggestions"]] == [
        "MON-00922", "BEA-01877", "DEL-00890",
    ]

    # Another tenant (empty catalog) never sees Acme's articles (SC-007).
    r = client.post(
        "/catalog/suggestions", json={"lines": [toner]}, headers=_auth(_signin("admin@walmart.com"))
    )
    assert r.json()["lines"][0]["suggestions"] == []

    loner = client.post(
        "/auth/signup", json={"email": "catalog-loner@example.com", "password": "secret123"}
    ).json()["access_token"]
    assert client.post(
        "/catalog/suggestions", json={"lines": [toner]}, headers=_auth(loner)
    ).status_code == 403


def test_request_catalog_links_snapshot_and_alternatives():
    # Toner lines use group 29: Acme's booking rule (spec 003) books toner under Hardware.
    from app.models import Article, Organization, Supplier

    with TestingSession() as db:
        mon = db.scalar(select(Article).where(Article.article_number == "MON-00922"))
        mon_id = str(mon.id)
        walmart = db.scalar(select(Organization).where(Organization.slug == "walmart"))
        foreign_supplier = Supplier(organization_id=walmart.id, name="Walmart Vendor")
        db.add(foreign_supplier)
        db.flush()
        foreign = Article(
            organization_id=walmart.id, article_number="WAL-1", supplier_id=foreign_supplier.id,
            description="Toner cartridge cyan", unit_price=1, unit="piece", quantity=1,
        )
        db.add(foreign)
        db.commit()
        foreign_id = str(foreign.id)

    token = _signin("requester@acme.com")
    linked = {
        "positionDescription": "Toner cartridge cyan", "unitPrice": 95.0, "amount": 10,
        "unit": "piece", "totalPrice": 950.0, "catalogArticleId": mon_id,
        "originalUnitPrice": 120.0,
    }
    unlinked = {
        "positionDescription": "Toner cartridge cyan", "unitPrice": 150.0, "amount": 5,
        "unit": "pieces", "totalPrice": 750.0,
    }
    payload = {
        "requestorName": "R", "titleShortDescription": "Toner", "vendorName": "Montclair Supply Corp.",
        "vatId": "", "commodityGroupId": 29, "totalCost": 1700.0, "department": "",
        "orderLines": [linked, unlinked],
    }
    r = client.post("/requests", json=payload, headers=_auth(token))
    assert r.status_code == 201, r.text
    created = r.json()
    first, second = created["order_lines"]
    assert (first["article_number"], first["article_supplier_name"]) == (
        "MON-00922", "Montclair Supply Corp."
    )
    assert (first["negotiated_unit_price"], first["original_unit_price"]) == (95.0, 120.0)
    assert first["potential_saving"] is None
    # Unlinked line: the cheaper agreement it ignored, for the buyer (FR-019).
    assert (second["alternative_article_number"], second["potential_saving"]) == (
        "MON-00922", 275.0
    )
    assert created["potential_saving_total"] == 275.0
    activity = client.get(f"/requests/{created['id']}/activity", headers=_auth(token)).json()
    assert any("1 of 2 lines use catalog agreements" in a["summary"] for a in activity)

    # A later catalog price change doesn't rewrite the submitted agreement.
    with TestingSession() as db:
        db.get(Article, mon.id).unit_price = 80
        db.commit()
    edit = dict(payload, title="Toner refill")
    del edit["titleShortDescription"]
    r = client.put(f"/requests/{created['id']}", json=edit, headers=_auth(token))
    assert r.status_code == 200, r.text
    assert r.json()["order_lines"][0]["negotiated_unit_price"] == 95.0
    with TestingSession() as db:
        db.get(Article, mon.id).unit_price = 95
        db.commit()

    # Another organization's article can't be linked (tenant isolation).
    bad = dict(payload, orderLines=[dict(linked, catalogArticleId=foreign_id)])
    r = client.post("/requests", json=bad, headers=_auth(token))
    assert r.status_code == 422 and r.json()["detail"] == "Unknown catalog article"


def test_catalog_usage_report_admin_only():
    from app.models import Article

    admin = _signin("admin@acme.com")
    before = client.get("/catalog/usage", headers=_auth(admin)).json()
    with TestingSession() as db:
        mon_id = str(db.scalar(select(Article.id).where(Article.article_number == "MON-00922")))
    lines = [
        {"positionDescription": "Toner cartridge cyan", "unitPrice": 95.0, "amount": 10,
         "unit": "piece", "totalPrice": 950.0, "catalogArticleId": mon_id,
         "originalUnitPrice": 120.0},
        {"positionDescription": "Toner cartridge cyan", "unitPrice": 150.0, "amount": 5,
         "unit": "pieces", "totalPrice": 750.0},
    ]
    r = client.post(
        "/requests",
        json={"requestorName": "A", "titleShortDescription": "Usage", "vendorName": "V",
              "vatId": "", "commodityGroupId": 29, "totalCost": 1700.0, "department": "",
              "orderLines": lines},
        headers=_auth(admin),
    )
    assert r.status_code == 201, r.text

    r = client.get("/catalog/usage", headers=_auth(admin))
    assert r.status_code == 200, r.text
    usage = r.json()
    assert usage["lineCount"] - before["lineCount"] == 2
    assert usage["linkedLineCount"] - before["linkedLineCount"] == 1
    # (120 - 95) x 10 realised; (150 - 95) x 5 missed.
    assert round(usage["realisedSavings"] - before["realisedSavings"], 2) == 250.0
    assert round(usage["missedSavings"] - before["missedSavings"], 2) == 275.0
    assert 0 < usage["linkedShare"] <= 1

    assert client.get("/catalog/usage", headers=_auth(_signin("buyer@acme.com"))).status_code == 403
    walmart = client.get("/catalog/usage", headers=_auth(_signin("admin@walmart.com"))).json()
    assert walmart["lineCount"] == 0
    r = client.get(
        "/catalog/usage?from=2026-10-10&to=2026-10-01", headers=_auth(_signin("admin@acme.com"))
    )
    assert r.status_code == 422


def _toner_request(**overrides) -> dict:
    payload = {
        "requestorName": "R", "titleShortDescription": "Toner", "vendorName": "Office Depot",
        "vatId": "", "commodityGroupId": 29, "totalCost": 480.0, "department": "",
        "orderLines": [
            {"positionDescription": "Toner cartridge black, high-yield, HP 59A", "unitPrice": 120.0,
             "amount": 4, "unit": "pieces", "totalPrice": 480.0}
        ],
    }
    payload.update(overrides)
    return payload


def test_classification_api_applies_org_rules_only():
    lines = {"lines": [{"description": "Cable ties nylon 8 in, black, pack of 100",
                        "quantity": 20, "unitPrice": 8.5, "totalPrice": 170.0}]}
    acme = client.post("/classification", json=lines, headers=_auth(_signin("requester@acme.com")))
    assert acme.status_code == 200, acme.text
    body = acme.json()
    assert (body["source"], body["commodityGroupId"], body["rule"]["name"]) == (
        "rule", 11, "Cable ties"
    )
    assert "booking rule" in body["rule"]["explanation"]

    walmart = client.post("/classification", json=lines, headers=_auth(_signin("admin@walmart.com")))
    assert walmart.json()["rule"] is None and walmart.json()["source"] is None  # no AI in tests


def test_requester_cannot_book_rule_covered_request_elsewhere():
    token = _signin("requester@acme.com")
    r = client.post("/requests", json=_toner_request(commodityGroupId=204), headers=_auth(token))
    assert r.status_code == 422
    assert r.json()["detail"] == "Booking rule 'Printer toner' requires commodity group 29 · Hardware."

    r = client.post("/requests", json=_toner_request(), headers=_auth(token))
    assert r.status_code == 201, r.text
    created = r.json()
    assert (created["commodity_source"], created["booking_rule_name"]) == ("rule", "Printer toner")
    assert created["booking_rule_line"].startswith("Toner cartridge black")

    # Edits are checked the same way (FR-005).
    edit = dict(_toner_request(), title="Toner", commodityGroupId=15)
    del edit["titleShortDescription"]
    r = client.put(f"/requests/{created['id']}", json=edit, headers=_auth(token))
    assert r.status_code == 422


def test_buyer_override_needs_reason_and_is_logged():
    token = _signin("buyer@acme.com")
    r = client.post("/requests", json=_toner_request(commodityGroupId=204), headers=_auth(token))
    assert r.status_code == 422
    assert "reason is required" in r.json()["detail"]

    r = client.post(
        "/requests",
        json=_toner_request(commodityGroupId=204, overrideReason="Toner for the print shop budget"),
        headers=_auth(token),
    )
    assert r.status_code == 201, r.text
    created = r.json()
    assert (created["commodity_source"], created["commodity_group_id"]) == ("override", 204)
    assert created["override_reason"] == "Toner for the print shop budget"
    activity = client.get(f"/requests/{created['id']}/activity", headers=_auth(token)).json()
    assert any(a["action"] == "commodity_override" and "print shop" in a["summary"] for a in activity)

    # A requester editing that request keeps the buyer's override.
    edit = dict(_toner_request(commodityGroupId=204), title="Toner (print shop)")
    del edit["titleShortDescription"]
    r = client.put(
        f"/requests/{created['id']}", json=edit, headers=_auth(_signin("requester@acme.com"))
    )
    assert r.status_code == 200, r.text
    assert r.json()["commodity_source"] == "override"


def test_other_orgs_and_unruled_items_are_unaffected():
    walmart = _signin("admin@walmart.com")
    r = client.post("/requests", json=_toner_request(commodityGroupId=204), headers=_auth(walmart))
    assert r.status_code == 201, r.text
    assert r.json()["commodity_source"] == "manual" and r.json()["booking_rule_name"] is None

    paper = _toner_request(
        commodityGroupId=201, commoditySource="system",
        orderLines=[{"positionDescription": "Copy paper letter size", "unitPrice": 49.0,
                     "amount": 3, "unit": "case", "totalPrice": 147.0}],
    )
    r = client.post("/requests", json=paper, headers=_auth(_signin("requester@acme.com")))
    assert r.status_code == 201 and r.json()["commodity_source"] == "system"


def test_booking_rule_management_admin_only_and_audited():
    admin = _signin("admin@acme.com")
    rules = client.get("/booking-rules", headers=_auth(admin)).json()
    assert {r["name"] for r in rules} >= {"Cable ties", "Printer toner", "Small software subscriptions"}
    assert client.get("/booking-rules", headers=_auth(_signin("buyer@acme.com"))).status_code == 403

    new_rule = {
        "name": "Label printer tape", "description": "Label tape is office supplies",
        "include_terms": ["label tape", "label printer tape"], "exclude_terms": [],
        "target_commodity_group_id": 15,
    }
    r = client.post("/booking-rules", json=new_rule, headers=_auth(admin))
    assert r.status_code == 201, r.text
    rule_id = r.json()["rule"]["id"]
    assert r.json()["rule"]["target_commodity_group_name"] == "Office Equipment"

    # The new rule applies to the next request right away (SC-006).
    lines = {"lines": [{"description": "Label printer tape 12 mm", "totalPrice": 30.0}]}
    r = client.post("/classification", json=lines, headers=_auth(_signin("requester@acme.com")))
    assert (r.json()["commodityGroupId"], r.json()["rule"]["name"]) == (15, "Label printer tape")

    assert client.post("/booking-rules", json=new_rule, headers=_auth(admin)).status_code == 409
    bad = dict(new_rule, name="Bad", target_commodity_group_id=999999)
    assert client.post("/booking-rules", json=bad, headers=_auth(admin)).status_code == 422
    overlap = dict(new_rule, name="Toner again", include_terms=["toner*"])
    r = client.post("/booking-rules", json=overlap, headers=_auth(admin))
    assert r.status_code == 201 and r.json()["warnings"]
    client.delete(f"/booking-rules/{r.json()['rule']['id']}", headers=_auth(admin))

    r = client.put(
        f"/booking-rules/{rule_id}", json=dict(new_rule, active=False), headers=_auth(admin)
    )
    assert r.status_code == 200 and r.json()["rule"]["active"] is False
    events = client.get("/booking-rules/events", headers=_auth(admin)).json()
    assert {"created", "updated", "deleted"} <= {e["action"] for e in events}
    assert any("Label printer tape" in e["summary"] for e in events)

    # Other organizations can't see or touch Acme's rules.
    walmart = _signin("admin@walmart.com")
    assert client.get("/booking-rules", headers=_auth(walmart)).json() == []
    assert client.delete(f"/booking-rules/{rule_id}", headers=_auth(walmart)).status_code == 404
    assert client.delete(f"/booking-rules/{rule_id}", headers=_auth(admin)).status_code == 204


def test_check_and_rebook_existing_requests():
    from app.models import ProcurementRequest

    token = _signin("requester@acme.com")
    created = client.post("/requests", json=_toner_request(), headers=_auth(token)).json()
    # Simulate a request booked before the rule existed.
    with TestingSession() as db:
        request = db.get(ProcurementRequest, uuid.UUID(created["id"]))
        request.commodity_group_id, request.commodity_source = 204, "manual"
        db.commit()

    admin = _signin("admin@acme.com")
    found = client.get("/booking-rules/check", headers=_auth(admin)).json()
    mine = [f for f in found if f["request_id"] == created["id"]]
    assert mine and (mine[0]["current_group_id"], mine[0]["mandated_group_id"]) == (204, 29)

    r = client.post(
        "/booking-rules/rebook", json={"requestIds": [created["id"]]}, headers=_auth(admin)
    )
    assert r.json() == {"rebooked": 1}
    after = client.get(f"/requests/{created['id']}", headers=_auth(admin)).json()
    assert (after["commodity_group_id"], after["commodity_source"]) == (29, "rule")
    activity = client.get(f"/requests/{created['id']}/activity", headers=_auth(admin)).json()
    assert any(a["action"] == "rebooked" for a in activity)
    assert client.get("/booking-rules/check", headers=_auth(_signin("buyer@acme.com"))).status_code == 403


if __name__ == "__main__":
    test_full_user_journey()
    test_pdf_parse()
    test_extraction_without_api_key()
    test_activity_log_and_document()
    test_commodity_groups_expanded()
    test_suppliers_seeded_with_empty_descriptions()
    test_seed_is_idempotent()
    test_demo_user_can_sign_in()
    test_approval_flow_with_roles()
    test_org_settings_required_fields()
    test_org_settings_admin_only()
    print("ALL SMOKE TESTS PASSED")
