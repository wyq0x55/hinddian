from __future__ import annotations

import pytest

from hinddian import notes as N


@pytest.fixture(params=[N.upsert_note, N.suggest_correction], ids=["upsert_note", "suggest_correction"])
def write(request):
    return request.param


def _note(title):
    return N.upsert_note({"type": "decision", "project": "P", "title": title, "scene": "部署",
                          "practice": title, "reason": "安全", "force_new": True})


def _snapshot(vault):
    return {str(path.relative_to(vault)): path.read_bytes() for path in vault.rglob("*.md")}


def test_update_adds_bidirectional_links_and_preserves_existing(vault, write):
    first, second, successor = [_note(title) for title in ("First", "Second", "Successor")]
    for predecessor in (first, second):
        result = write({"action": "update", "id": successor["id"], "supersedes": [predecessor["id"]]})
        assert result["ok"] and result["action"] == "update"
        old = N.get_note(predecessor["id"])
        assert old["status"] == "superseded" and old["superseded_by"] == successor["id"]
        assert old["updated"] == N.today() and "已被" in old["text"]
    current = N.get_note(successor["id"])
    assert current["supersedes"] == [first["id"], second["id"]]
    assert current["status"] == "active"
    for payload in ({"supersedes": []}, {"reason": "修订"}):
        assert write({"action": "update", "id": successor["id"], **payload})["ok"]
        assert N.get_note(successor["id"])["supersedes"] == current["supersedes"]


def test_existing_successor_reuses_note_and_is_idempotent(vault, write):
    old, successor = [_note(title) for title in ("Old", "Successor")]
    path = vault / (successor["path"] + ".md")
    path.write_text(path.read_text().replace("status: active", "reviewer: alice\nstatus: active")
                    + "\n## 人工补充\n保留正文\n", encoding="utf-8")
    original = N.get_note(successor["id"])
    paths = set(_snapshot(vault))
    payload = {"action": "supersede", "successor_id": successor["id"], "supersedes": [old["id"], old["id"]]}
    assert write(payload)["ok"]
    result = write(payload)
    assert result["ok"] and result["action"] == "supersede"
    assert result["id"] == successor["id"] and result["path"] == successor["path"]
    assert set(_snapshot(vault)) == paths
    current = N.get_note(successor["id"])
    assert current["supersedes"] == [old["id"]] and current["status"] == "active"
    assert all(current[field] == original[field] for field in ("title", "scene", "practice", "reason"))
    assert "reviewer: alice" in current["text"] and "保留正文" in current["text"]
    assert N.get_note(old["id"])["superseded_by"] == successor["id"]


@pytest.mark.parametrize("action", ["update", "supersede"])
def test_reparent_removes_stale_reverse_link(vault, write, action):
    old, sibling, previous, successor = [_note(title) for title in ("Old", "Sibling", "Previous", "Successor")]
    assert N.upsert_note({"action": "update", "id": previous["id"],
                          "supersedes": [old["id"], sibling["id"]]})["ok"]
    payload = {"action": action, "supersedes": [old["id"]],
               "id" if action == "update" else "successor_id": successor["id"]}
    assert write(payload)["ok"]
    assert N.get_note(old["id"])["superseded_by"] == successor["id"]
    assert N.get_note(successor["id"])["supersedes"] == [old["id"]]
    assert N.get_note(previous["id"])["supersedes"] == [sibling["id"]]
    assert N.get_note(sibling["id"])["superseded_by"] == previous["id"]


@pytest.mark.parametrize("predecessors,error", [
    (None, "invalid_supersedes"), ("missing", "invalid_supersedes"),
    ({"id": "missing"}, "invalid_supersedes"), ([1], "invalid_supersedes"),
    ([""], "invalid_supersedes"), ([" missing "], "invalid_supersedes"),
    (["missing"], "supersedes_not_found"),
])
@pytest.mark.parametrize("action", ["update", "supersede", "new_supersede"])
def test_invalid_predecessors_do_not_write(vault, write, predecessors, error, action):
    successor = _note("Successor")
    payload = {"action": "supersede" if action == "new_supersede" else action, "supersedes": predecessors}
    if action == "update":
        payload.update(id=successor["id"], practice="must not write")
    elif action == "supersede":
        payload["successor_id"] = successor["id"]
    else:
        payload.update(type="decision", project="P", title="New", scene="s", practice="p", reason="r")
    before = _snapshot(vault)
    result = write(payload)
    assert result["ok"] is False and result["error"] == error
    assert _snapshot(vault) == before


@pytest.mark.parametrize("payload,error", [
    ({"action": "update", "id": "missing"}, "update_needs_existing_id"),
    ({"action": "update"}, "update_needs_existing_id"),
    ({"action": "update", "id": ["bad"]}, "invalid_id"),
    ({"action": "supersede", "successor_id": "missing"}, "successor_not_found"),
    ({"action": "supersede", "successor_id": None}, "invalid_successor_id"),
    ({"action": "supersede", "successor_id": ["bad"]}, "invalid_successor_id"),
    ({"action": "update", "successor_id": "missing"}, "successor_id_requires_supersede"),
    ({"action": "supersede", "supersedes": []}, "supersede_needs_predecessors"),
    ({"action": "obsolete", "supersedes": []}, "supersedes_not_supported"),
])
def test_invalid_targets_do_not_create_notes(vault, write, payload, error):
    before = _snapshot(vault)
    result = write(payload)
    assert result["ok"] is False and result["error"] == error
    assert _snapshot(vault) == before


def test_mixed_valid_and_missing_predecessors_are_rejected_before_any_write(vault, write):
    old, successor = [_note(title) for title in ("Old", "Successor")]
    before = _snapshot(vault)
    result = write({"action": "update", "id": successor["id"], "practice": "changed",
                    "supersedes": [old["id"], "missing"]})
    assert result == {"ok": False, "error": "supersedes_not_found", "ids": ["missing"]}
    assert _snapshot(vault) == before


def test_self_supersession_is_rejected(vault, write):
    successor = _note("Successor")
    before = _snapshot(vault)
    result = write({"action": "supersede", "successor_id": successor["id"], "supersedes": [successor["id"]]})
    assert result["error"] == "self_supersession" and result["ok"] is False
    assert _snapshot(vault) == before


def test_retired_successor_and_content_arguments_are_rejected(vault, write):
    old, successor = [_note(title) for title in ("Old", "Successor")]
    payload = {"action": "supersede", "successor_id": successor["id"], "supersedes": [old["id"]]}
    before = _snapshot(vault)
    assert write({**payload, "title": "Ignored?"})["error"] == "successor_link_only"
    assert _snapshot(vault) == before
    assert N.upsert_note({"action": "obsolete", "id": successor["id"]})["ok"]
    before = _snapshot(vault)
    assert write(payload)["error"] == "successor_not_active"
    assert _snapshot(vault) == before


@pytest.mark.parametrize("reverse_only", [False, True])
def test_transitive_cycles_are_rejected_even_with_one_way_historical_links(vault, write, reverse_only):
    successor, middle, predecessor = [_note(title) for title in ("Successor", "Middle", "Predecessor")]
    for child, parent in ((successor, middle), (middle, predecessor)):
        notes = N.load_notes()
        note = notes[child["id"] if reverse_only else parent["id"]]
        if reverse_only:
            path = vault / (note["path"] + ".md")
            path.write_text(path.read_text().replace("status: active", f"status: active\nsuperseded_by: {parent['id']}"),
                            encoding="utf-8")
        else:
            note["supersedes"] = [child["id"]]
            N._write(note, notes)
    before = _snapshot(vault)
    result = write({"action": "update", "id": successor["id"], "supersedes": [predecessor["id"]]})
    assert result["error"] == "supersession_cycle" and result["ok"] is False
    assert _snapshot(vault) == before


@pytest.mark.parametrize("tool", ["upsert_note", "suggest_correction"])
@pytest.mark.parametrize("action", ["update", "supersede"])
def test_mcp_forwards_supersession_parameters(vault, monkeypatch, tool, action):
    from hinddian import memory_mcp

    calls = []

    def local_vault(operation, **kwargs):
        calls.append((operation, kwargs["payload"]))
        return getattr(N, operation)(kwargs["payload"])

    monkeypatch.setattr(memory_mcp, "vault", local_vault)
    old, successor = [_note(title) for title in ("Old", "Successor")]
    payload = {"action": action, "supersedes": [old["id"]],
               "id" if action == "update" else "successor_id": successor["id"]}
    result = memory_mcp.call_tool(tool, payload)
    assert result["ok"] and result["id"] == successor["id"]
    assert calls == [(tool, payload)]
    assert N.get_note(successor["id"])["supersedes"] == [old["id"]]
    assert N.get_note(old["id"])["superseded_by"] == successor["id"]


def test_mcp_schemas_expose_existing_successor_and_additive_links():
    from hinddian import memory_mcp

    for tool in memory_mcp.TOOLS:
        if tool["name"] in ("upsert_note", "suggest_correction"):
            properties = tool["inputSchema"]["properties"]
            assert properties["successor_id"]["type"] == "string"
            assert "supersede only" in properties["successor_id"]["description"]
            assert "preserving existing links" in properties["supersedes"]["description"]
