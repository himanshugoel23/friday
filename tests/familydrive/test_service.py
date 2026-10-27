"""FamilyDrive over the in-memory FakeDrive: tree, filing, lookup, sharing, disconnect."""

from __future__ import annotations

import json

import pytest
from sqlalchemy import text

from friday.docunderstand.models import DocType
from friday.familydrive import tree
from friday.familydrive.ports import DriveError, DriveNeedsReconnect, DriveNotLinked
from friday.familydrive.service import FamilyDriveError
from tests.familydrive.conftest import JPEG, PDF

# ----------------------------------------------------------------------------- switch + link


async def test_switch_off_by_default_and_nothing_happens(settings, repos, hub, clock, alice):
    from friday.familydrive.service import FamilyDrive

    assert settings.family_drive_enabled is False
    off = FamilyDrive(settings, repos, hub.factory, clock=clock)
    with pytest.raises(FamilyDriveError) as e:
        await off.link(alice.id)
    assert e.value.code == "disabled"
    assert hub.drives == {}  # not even a Drive object was created
    # a user can always delete: disconnect works with the switch off
    res = await off.disconnect(alice.id)
    assert res.links == 0


async def test_operations_need_a_link(svc, alice, mk):
    doc = await mk(alice.id)
    with pytest.raises(DriveNotLinked):
        await svc.file_document(alice.id, doc.id, PDF)
    st = await svc.status(alice.id)
    assert st.state == "not_linked"


async def test_link_creates_root_once(svc, hub, alice):
    a = await svc.link(alice.id)
    b = await svc.link(alice.id)
    assert a.root_link == b.root_link and a.state == "active"
    assert [f.name for f in hub.for_user(alice.id).folders()] == ["Friday"]


# ----------------------------------------------------------------------------- folder tree


async def test_full_tree_is_structured_and_idempotent(svc, hub, alice):
    await svc.link(alice.id)
    first = await svc.ensure_tree(alice.id, person="Asha", trip="Goa Nov 2026")
    n_folders = len(hub.for_user(alice.id).folders())
    second = await svc.ensure_tree(alice.id, person="Asha", trip="Goa Nov 2026")
    assert first == second
    assert len(hub.for_user(alice.id).folders()) == n_folders  # nothing duplicated
    drive = hub.for_user(alice.id)
    paths = sorted(drive.path_of(f.id) for f in drive.folders())
    assert "Friday/Family/Asha/Passports" in paths and "Friday/Family/Asha/Bills" in paths
    assert "Friday/Trips/Goa Nov 2026/Tickets" in paths
    assert "Friday/Trips/Goa Nov 2026/Hotel" in paths
    assert "Friday/Trips/Goa Nov 2026/Insurance" in paths
    assert "Friday/Trips/Goa Nov 2026/Bills" in paths
    # 1 root + family + trips + 1 person + 6 subs + 1 trip + 4 subs
    assert n_folders == 1 + 2 + 1 + 6 + 1 + 4


async def test_tree_survives_lost_local_cache(svc, hub, repos, alice):
    """A retry after a crash (cache rows lost) finds the folders by their Drive-side key."""
    await svc.link(alice.id)
    await svc.ensure_tree(alice.id, person="Asha")
    n = len(hub.for_user(alice.id).folders())
    for key in ("root", "family", tree.person_key("Asha")):
        await repos.family_drive.delete_folders(alice.id, key)
    await svc.ensure_tree(alice.id, person="Asha")
    assert len(hub.for_user(alice.id).folders()) == n


async def test_folder_the_user_trashed_is_recreated_below_a_fresh_parent(svc, hub, alice):
    await svc.link(alice.id)
    out = await svc.ensure_tree(alice.id, person="Asha")
    drive = hub.for_user(alice.id)
    asha = next(f for f in drive.folders() if f.name == "Asha")
    drive.user_trashes(asha.id)
    again = await svc.ensure_tree(alice.id, person="Asha")
    assert again != out  # new folder ids
    live = [f for f in drive.folders() if not f.trashed and f.name == "Asha"]
    assert len(live) == 1
    assert len([f for f in drive.folders() if not f.trashed and f.name == "Passports"]) == 1


def test_folder_names_are_cleaned_and_keys_are_stable():
    cleaned = tree.clean_folder_name("../../Mom/Dad\x00 <b>", "x")
    assert not set(cleaned) & set("/\\<>\x00")
    assert "/" not in tree.clean_folder_name("a/b\\c", "x")
    assert tree.clean_folder_name("   ", "Fallback") == "Fallback"
    assert tree.clean_folder_name("Passport 123456789", "x") == "Passport"  # no long digit runs
    assert tree.person_key("Asha ") == tree.person_key("asha")
    assert tree.person_key("आशा") != tree.person_key("Asha")
    assert len(tree.person_key("x" * 500)) < 100


# ----------------------------------------------------------------------------- filing + pointers


async def test_file_document_uploads_and_keeps_only_a_pointer(svc, hub, repos, alice, mk):
    await svc.link(alice.id)
    doc = await mk(alice.id)
    out = await svc.file_document(alice.id, doc.id, PDF, trip="Goa Nov 2026")
    assert out.name == "2026-11-14 DEL-GOI IndiGo.pdf"
    assert out.path == "Friday/Trips/Goa Nov 2026/Tickets"
    drive = hub.for_user(alice.id)
    f = drive.files()[0]
    assert f.data == PDF and drive.path_of(f.id) == "Friday/Trips/Goa Nov 2026/Tickets/" + out.name
    assert out.link.endswith(f"/{f.id}/view")
    stored = await repos.documents.get(alice.id, doc.id)
    assert stored.pointer_kind == "gdrive"
    assert json.loads(stored.pointer_ref)["id"] == f.id
    # pointer only: no byte of the file, no PNR in the pointer, nothing readable in the DB
    chunks: list[str] = []
    async with repos.db.session() as s:
        for table in ("documents", "document_fields", "drive_links", "drive_folders"):
            for r in (await s.execute(text(f"select * from {table}"))).all():  # noqa: S608
                chunks += [str(c) for c in r]
    dump = " ".join(chunks)
    assert "invented test file" not in dump and f.id not in dump  # ids are encrypted at rest
    cols = set()
    for t in ("documents", "drive_links", "drive_folders", "drive_shares"):
        cols |= {r[1] for r in await _pragma(repos, t)}
    assert not {c for c in cols if c in ("data", "content", "blob", "bytes", "file")}


async def _pragma(repos, table: str):  # noqa: ANN202
    async with repos.db.session() as s:
        return (await s.execute(text(f"pragma table_info({table})"))).all()  # noqa: S608


async def test_second_call_is_idempotent_no_second_upload(svc, hub, alice, mk):
    await svc.link(alice.id)
    doc = await mk(alice.id)
    a = await svc.file_document(alice.id, doc.id, PDF)
    b = await svc.file_document(alice.id, doc.id, PDF)
    assert b.already_filed and a.link == b.link
    assert hub.for_user(alice.id).count("upload") == 1


async def test_failed_upload_stores_no_pointer_and_retry_works(svc, hub, repos, alice, mk):
    await svc.link(alice.id)
    doc = await mk(alice.id)
    drive = hub.for_user(alice.id)
    drive.fail_upload_once = True
    with pytest.raises(DriveError) as e:
        await svc.file_document(alice.id, doc.id, PDF)
    assert e.value.code == "unreachable"
    stored = await repos.documents.get(alice.id, doc.id)
    assert stored.pointer_kind is None and stored.pointer_ref is None
    assert drive.files() == []
    out = await svc.file_document(alice.id, doc.id, PDF)  # the user sends it again
    assert len(drive.files()) == 1 and not out.already_filed


async def test_lost_response_retry_finds_the_uploaded_file(svc, hub, alice, mk):
    """The upload reached Drive but the answer was lost: the retry must not upload twice."""
    await svc.link(alice.id)
    doc = await mk(alice.id)
    drive = hub.for_user(alice.id)
    scope, sub = tree.destination(DocType.FLIGHT, has_trip=True)
    await svc.ensure_tree(alice.id, trip="T")
    parent = next(f for f in drive.folders() if f.name == "Tickets")
    await drive.upload(
        "x.pdf", PDF, "application/pdf", parent.id, key=tree.file_key(alice.id, doc.id)
    )
    await svc.file_document(alice.id, doc.id, PDF, trip="T")
    assert len(drive.files()) == 1


async def test_pointer_write_failure_trashes_the_orphan(svc, hub, repos, alice, mk, monkeypatch):
    await svc.link(alice.id)
    doc = await mk(alice.id)

    async def boom(*a, **k):  # noqa: ANN002, ANN003
        raise RuntimeError("db down")

    monkeypatch.setattr(repos.documents, "set_pointer", boom)
    with pytest.raises(RuntimeError):
        await svc.file_document(alice.id, doc.id, PDF)
    assert all(f.trashed for f in hub.for_user(alice.id).files())


async def test_input_checks(svc, hub, alice, mk, clock):
    from friday.docunderstand.models import DocStatus

    await svc.link(alice.id)
    doc = await mk(alice.id)
    for bad, code in (
        (b"", "bad_file"),
        (b"MZ not a document", "bad_file"),
        (JPEG, "hash_mismatch"),  # valid type but not the confirmed document
        (PDF + b"x" * (9 * 1024 * 1024), "too_large"),
    ):
        with pytest.raises(FamilyDriveError) as e:
            await svc.file_document(alice.id, doc.id, bad)
        assert e.value.code in (code, "hash_mismatch" if code == "too_large" else code)
    with pytest.raises(FamilyDriveError) as e:
        await svc.file_document(alice.id, doc.id, PDF, mime="image/png")  # declared != sniffed
    assert e.value.code == "bad_file"
    pending = await mk(alice.id, status=DocStatus.PENDING)
    with pytest.raises(FamilyDriveError) as e:
        await svc.file_document(alice.id, pending.id, PDF)
    assert e.value.code == "not_confirmed"
    assert hub.for_user(alice.id).files() == []


async def test_file_names_never_carry_untrusted_text_or_id_numbers(svc, hub, alice, mk):
    await svc.link(alice.id)
    doc = await mk(
        alice.id,
        fields={
            "airline": "IndiGo ../../etc/passwd\x00 9876543210123",
            "from_iata": "DEL",
            "to_iata": "GOI",
            "dep_local": "2026-11-14T06:30",
        },
    )
    out = await svc.file_document(alice.id, doc.id, PDF)
    assert "/" not in out.name and "\x00" not in out.name and "9876543210123" not in out.name
    assert out.name.endswith(".pdf") and out.name.startswith("2026-11-14 DEL-GOI")
    # a passport file name has the first name and the expiry date, never the number
    pp = await mk(
        alice.id,
        doc_type=DocType.PASSPORT,
        fields={"given_name": "Asha", "number_masked": "******567", "expiry_date": "2031-02-03"},
    )
    out2 = await svc.file_document(alice.id, pp.id, PDF, person="Asha")
    assert out2.name == "Passport Asha exp 2031-02-03.pdf"
    assert "567" not in out2.name and out2.path == "Friday/Family/Asha/Passports"


async def test_routing_by_document_type(svc, hub, alice, mk):
    await svc.link(alice.id)
    cases = [
        (DocType.HOTEL, {"property_name": "Sea View", "check_in_date": "2026-11-14"}, "Hotel"),
        (DocType.BILL, {"biller": "Power Co", "due_date": "2026-12-01"}, "Bills"),
        (DocType.GENERIC, {"title": "Note"}, "Other"),
    ]
    for dt, fields, leaf in cases:
        d = await mk(alice.id, doc_type=dt, fields=fields)
        out = await svc.file_document(alice.id, d.id, PDF, person="Asha", trip="Goa")
        if dt is DocType.GENERIC:
            assert out.path.endswith("Asha/Other")
        else:
            assert out.path.endswith(f"Goa/{leaf}")


# ----------------------------------------------------------------------------- where is my X


async def test_where_is_returns_drive_links_and_ranks(svc, alice, mk):
    await svc.link(alice.id)
    pp = await mk(
        alice.id,
        doc_type=DocType.PASSPORT,
        fields={"given_name": "Asha", "expiry_date": "2031-02-03"},
    )
    pp2 = await mk(
        alice.id,
        doc_type=DocType.PASSPORT,
        fields={"given_name": "Meera", "expiry_date": "2030-01-01"},
        data=PDF,
    )
    tk = await mk(alice.id)
    for d, kw in ((pp, {"person": "Asha"}), (pp2, {"person": "Meera"}), (tk, {"trip": "Goa"})):
        await svc.file_document(alice.id, d.id, PDF, **kw)
    hits = await svc.where_is(alice.id, "Asha ka passport kahan hai")
    assert [h.document_id for h in hits] == [pp.id]  # the name narrows it down
    assert hits[0].doc_type == "passport" and "drive.google.com" in hits[0].link
    both = await svc.where_is(alice.id, "passport")
    assert {h.document_id for h in both} == {pp.id, pp2.id}
    assert [h.document_id for h in await svc.where_is(alice.id, "flight ticket")] == [tk.id]
    assert await svc.where_is(alice.id, "hotel") == []
    assert await svc.where_is(alice.id, "मेरा पासपोर्ट")  # Devanagari keyword


async def test_where_is_drops_a_dangling_pointer(svc, hub, repos, alice, mk):
    await svc.link(alice.id)
    doc = await mk(alice.id)
    out = await svc.file_document(alice.id, doc.id, PDF)
    drive = hub.for_user(alice.id)
    drive.user_deletes(drive.files()[0].id)  # the user deleted it in Drive
    assert await svc.where_is(alice.id, "ticket") == []
    assert (await repos.documents.get(alice.id, doc.id)).pointer_ref is None
    assert out.document_id == doc.id


async def test_where_is_when_drive_is_down_still_gives_the_link_unverified(svc, hub, alice, mk):
    await svc.link(alice.id)
    doc = await mk(alice.id)
    await svc.file_document(alice.id, doc.id, PDF)
    hub.for_user(alice.id).set_failure("unreachable")
    hits = await svc.where_is(alice.id, "ticket")
    assert len(hits) == 1 and hits[0].verified is False


async def test_fetch_document_streams_back_into_memory(svc, alice, mk):
    await svc.link(alice.id)
    doc = await mk(alice.id)
    await svc.file_document(alice.id, doc.id, PDF)
    data, name = await svc.fetch_document(alice.id, doc.id)
    assert data == PDF and name.endswith(".pdf")


# ----------------------------------------------------------------------------- needs_reconnect


async def test_dead_token_marks_needs_reconnect_and_nothing_is_kept(svc, hub, repos, alice, mk):
    await svc.link(alice.id)
    doc = await mk(alice.id)
    hub.for_user(alice.id).fail = DriveNeedsReconnect("x")
    with pytest.raises(DriveNeedsReconnect):
        await svc.file_document(alice.id, doc.id, PDF)
    assert (await svc.status(alice.id)).state == "needs_reconnect"
    hub.for_user(alice.id).set_failure(None)
    with pytest.raises(DriveNeedsReconnect):  # blocked until the user reconnects
        await svc.file_document(alice.id, doc.id, PDF)
    assert (await repos.documents.get(alice.id, doc.id)).pointer_ref is None
    await svc.link(alice.id)  # reconnect heals
    assert (await svc.status(alice.id)).state == "active"


# ----------------------------------------------------------------------------- sharing


async def test_share_needs_owner_approval_and_shows_the_email(svc, hub, alice):
    await svc.link(alice.id)
    req = await svc.request_share(alice.id, "  Mom.Example@Gmail.com ")
    assert req.email == "mom.example@gmail.com" and req.status == "pending"
    assert hub.for_user(alice.id).count("share") == 0  # asking changes nothing in Drive
    done = await svc.approve_share(alice.id, req.id)
    assert done.status == "shared" and done.permission_id
    root = next(f for f in hub.for_user(alice.id).folders() if f.name == "Friday")
    assert list(root.permissions.values()) == [("mom.example@gmail.com", "viewer")]
    # asking again for the same person does not create a second request
    again = await svc.request_share(alice.id, "mom.example@gmail.com")
    assert again.id == req.id


async def test_share_requests_are_validated_and_expire(svc, hub, repos, clock, alice):
    await svc.link(alice.id)
    for bad in ("not-an-email", "a@b", "x@y.com;z@y.com", ""):
        with pytest.raises(FamilyDriveError):
            await svc.request_share(alice.id, bad)
    with pytest.raises(FamilyDriveError):
        await svc.request_share(alice.id, "ok@example.com", role="owner")
    req = await svc.request_share(alice.id, "ok@example.com", role="editor")
    clock.advance(days=8)
    with pytest.raises(FamilyDriveError) as e:
        await svc.approve_share(alice.id, req.id)
    assert e.value.code == "expired"
    assert hub.for_user(alice.id).count("share") == 0


async def test_decline_and_revoke(svc, hub, alice):
    await svc.link(alice.id)
    r1 = await svc.request_share(alice.id, "one@example.com")
    assert await svc.decline_share(alice.id, r1.id)
    with pytest.raises(FamilyDriveError):
        await svc.approve_share(alice.id, r1.id)  # declined is final
    r2 = await svc.request_share(alice.id, "two@example.com")
    await svc.approve_share(alice.id, r2.id)
    assert await svc.revoke_share(alice.id, r2.id)
    root = next(f for f in hub.for_user(alice.id).folders() if f.name == "Friday")
    assert root.permissions == {}


async def test_share_is_off_unless_its_own_switch_is_on(dsettings, repos, hub, clock, alice):
    from friday.familydrive.service import FamilyDrive

    s = FamilyDrive(
        dsettings.model_copy(update={"family_drive_sharing_enabled": False}),
        repos,
        hub.factory,
        clock=clock,
    )
    await s.link(alice.id)
    with pytest.raises(FamilyDriveError) as e:
        await s.request_share(alice.id, "x@example.com")
    assert e.value.code == "sharing_disabled"


async def test_failed_share_stays_pending_so_the_owner_can_retry(svc, hub, alice):
    await svc.link(alice.id)
    req = await svc.request_share(alice.id, "x@example.com")
    drive = hub.for_user(alice.id)
    drive.set_failure("unreachable")
    with pytest.raises(DriveError):
        await svc.approve_share(alice.id, req.id)
    drive.set_failure(None)
    assert (await svc.approve_share(alice.id, req.id)).status == "shared"


# ----------------------------------------------------------------------------- disconnect


async def test_disconnect_deletes_our_pointers_not_the_users_files(svc, hub, repos, alice, mk):
    await svc.link(alice.id)
    d1, d2 = await mk(alice.id), await mk(alice.id, doc_type=DocType.GENERIC, fields={"title": "n"})
    await svc.file_document(alice.id, d1.id, PDF)
    kept = await mk(
        alice.id, doc_type=DocType.BILL, fields={"biller": "B", "due_date": "2026-12-01"}
    )
    await svc.request_share(alice.id, "x@example.com")
    drive = hub.for_user(alice.id)
    files_before = {f.id for f in drive.files()}
    res = await svc.disconnect(alice.id)
    assert (res.pointers, res.links, res.shares) == (1, 1, 1) and res.folders >= 3
    assert {f.id for f in drive.files()} == files_before  # the user's files are untouched
    assert not any(f.trashed for f in drive.files() + drive.folders())
    assert drive.count("trash") == 0
    assert await repos.documents.get(alice.id, d1.id) is None  # pointer + its fields are gone
    assert await repos.documents.get(alice.id, d2.id) is not None  # unfiled documents stay
    assert await repos.documents.get(alice.id, kept.id) is not None
    assert (await svc.status(alice.id)).state == "not_linked"
    assert await repos.family_drive.count_folders(alice.id) == 0
    async with repos.db.session() as s:
        assert (
            await s.execute(
                text("select count(*) from document_fields where document_id=:d"), {"d": d1.id}
            )
        ).scalar_one() == 0
    with pytest.raises(DriveNotLinked):
        await svc.file_document(alice.id, d2.id, PDF)


async def test_disconnect_works_with_drive_down_and_trashing_is_explicit(svc, hub, alice, mk):
    await svc.link(alice.id)
    drive = hub.for_user(alice.id)
    drive.set_failure("unreachable")
    res = await svc.disconnect(alice.id, trash_root=True)  # best effort; local rows go anyway
    assert res.links == 1 and res.root_trashed is False
    drive.set_failure(None)
    await svc.link(alice.id)
    res = await svc.disconnect(alice.id, trash_root=True)
    assert res.root_trashed is True
    assert next(f for f in drive.folders() if f.name == "Friday").trashed


# ----------------------------------------------------------------------------- isolation


async def test_wrong_user_reaches_nothing(svc, hub, repos, alice, bob, mk):
    await svc.link(alice.id)
    await svc.link(bob.id)
    doc = await mk(alice.id)
    await svc.file_document(alice.id, doc.id, PDF, trip="Goa")
    # bob cannot file, find, fetch, share-approve or disconnect alice's things
    with pytest.raises(FamilyDriveError) as e:
        await svc.file_document(bob.id, doc.id, PDF)
    assert e.value.code == "unknown_document"
    assert await svc.where_is(bob.id, "ticket") == []
    with pytest.raises(FamilyDriveError):
        await svc.fetch_document(bob.id, doc.id)
    req = await svc.request_share(alice.id, "x@example.com")
    with pytest.raises(FamilyDriveError) as e2:
        await svc.approve_share(bob.id, req.id)
    assert e2.value.code == "unknown_share"
    assert not await svc.decline_share(bob.id, req.id)
    assert await svc.list_shares(bob.id) == []
    await svc.disconnect(bob.id)
    assert (await svc.status(alice.id)).state == "active"
    assert (await repos.documents.get(alice.id, doc.id)).pointer_kind == "gdrive"
    # each user has a separate Drive
    assert hub.for_user(bob.id).files() == []
    assert len(hub.for_user(alice.id).files()) == 1


async def test_two_users_same_names_get_separate_trees(svc, hub, alice, bob):
    await svc.link(alice.id)
    await svc.link(bob.id)
    await svc.ensure_tree(alice.id, person="Asha")
    await svc.ensure_tree(bob.id, person="Asha")
    assert len(hub.for_user(alice.id).folders()) == len(hub.for_user(bob.id).folders())
    assert {f.id for f in hub.for_user(alice.id).folders()} != set()
    assert tree.drive_key(alice.id, "root") != tree.drive_key(bob.id, "root")


async def test_log_lines_carry_no_names_ids_or_emails(svc, hub, alice, mk, log_capture):
    await svc.link(alice.id)
    hub.for_user(alice.id).set_failure("needs_reconnect")
    doc = await mk(alice.id)
    with pytest.raises(DriveError):
        await svc.file_document(alice.id, doc.id, PDF, person="Asha Private", trip="Secret Trip")
    logs = " ".join(r.getMessage() for r in log_capture.records)
    assert "Asha" not in logs and "Secret" not in logs and "IndiGo" not in logs
