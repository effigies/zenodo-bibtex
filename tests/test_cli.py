import json

import pytest
from typer.testing import CliRunner

from zenodo_bibtex import cli, serialize
from zenodo_bibtex.cli import app, load_records
from zenodo_bibtex.serialize import serialize_records

runner = CliRunner()

RECORD = {
    "id": "1",
    "pids": {"doi": {"identifier": "10.5281/zenodo.1"}},
    "metadata": {
        "resource_type": {"id": "software"},
        "title": "T",
        "publication_date": "2026-08-01",
        "creators": [{"person_or_org": {"name": "Roe, Ann", "family_name": "Roe"}}],
    },
}


def test_load_records_accepts_a_bare_list():
    assert load_records([RECORD]) == [RECORD]


def test_load_records_accepts_the_fetch_envelope():
    assert load_records({"records": [RECORD]}) == [RECORD]


def test_load_records_accepts_a_raw_zenodo_response():
    assert load_records({"hits": {"hits": [RECORD]}}) == [RECORD]


def test_load_records_rejects_an_unrecognised_shape():
    with pytest.raises(ValueError, match="unrecognised"):
        load_records({"nope": 1})


def test_convert_reads_stdin_and_writes_bibtex():
    result = runner.invoke(app, ["convert"], input=json.dumps([RECORD]))
    assert result.exit_code == 0
    assert result.stdout.startswith("@software{roe_2026_1,")
    assert result.stdout.endswith("}\n")


def test_convert_accepts_the_wrapping_option():
    result = runner.invoke(
        app, ["convert", "--wrapping", "fixed"], input=json.dumps([RECORD])
    )
    assert result.exit_code == 0


def test_convert_reports_a_bad_record_and_still_emits_the_others():
    payload = json.dumps([RECORD, {"id": "2"}])
    result = runner.invoke(app, ["convert"], input=payload)
    assert result.exit_code != 0
    assert "@software{roe_2026_1," in result.stdout
    assert "2" in result.stderr


def test_convert_rejects_invalid_json():
    result = runner.invoke(app, ["convert"], input="not json")
    assert result.exit_code != 0


def test_convert_survives_a_record_with_null_metadata():
    # "metadata": null is key-present-value-null, distinct from the
    # key-missing case already covered above; it reaches fields.py through a
    # different path (record.get("metadata", {}) returns None, not {}, when
    # the key exists) and must not take the whole bibliography down with it.
    payload = json.dumps([RECORD, {"id": "2", "metadata": None}])
    result = runner.invoke(app, ["convert"], input=payload)
    assert result.exit_code != 0
    assert "@software{roe_2026_1," in result.stdout
    assert "2" in result.stderr


def test_convert_handles_a_non_dict_record_without_crashing():
    payload = json.dumps([RECORD, [1, 2, 3]])
    result = runner.invoke(app, ["convert"], input=payload)
    assert result.exit_code != 0
    assert "@software{roe_2026_1," in result.stdout
    assert "<unknown>" in result.stderr


def test_fetch_happy_path_emits_the_records_envelope(monkeypatch):
    monkeypatch.setenv("ZENODO_TOKEN", "test-token")
    calls = {}

    def stub(query, *, client, base_url):
        calls["query"] = query
        calls["base_url"] = base_url
        calls["auth"] = client.headers.get("authorization")
        return [RECORD]

    monkeypatch.setattr(cli, "fetch_records", stub)
    result = runner.invoke(app, ["fetch", "--orcid", "0000-0002-6533-164X"])
    assert result.exit_code == 0
    assert json.loads(result.stdout) == {"records": [RECORD]}
    assert calls["query"] == "creators.orcid:0000-0002-6533-164X"
    assert calls["auth"] == "Bearer test-token"


def test_fetch_requires_a_token(monkeypatch):
    monkeypatch.delenv("ZENODO_TOKEN", raising=False)
    result = runner.invoke(app, ["fetch", "--orcid", "0000-0000-0000-0000"])
    assert result.exit_code != 0
    assert "ZENODO_TOKEN" in result.stderr


def test_fetch_requires_exactly_one_of_query_or_orcid(monkeypatch):
    monkeypatch.setenv("ZENODO_TOKEN", "x")
    result = runner.invoke(app, ["fetch"])
    assert result.exit_code != 0


def test_convert_output_is_exactly_what_serialize_records_produces():
    # The document format has one owner. `convert` used to hardcode its own
    # "\n\n".join(...) while serialize_records -- and the ENTRY_SEPARATOR
    # docstring describing the contract -- were imported by nothing under
    # src/, so the only test of the format exercised a function the CLI never
    # called.
    second = {**RECORD, "id": "2", "pids": {"doi": {"identifier": "10.5281/zenodo.2"}}}
    payload = json.dumps([RECORD, second])

    result = runner.invoke(app, ["convert"], input=payload)

    assert result.exit_code == 0
    assert result.stdout == serialize_records([RECORD, second])


def test_convert_honours_the_entry_separator(monkeypatch):
    # Proves ownership rather than coincidence: changing the constant must
    # change what a user sees.
    monkeypatch.setattr(serialize, "ENTRY_SEPARATOR", "\n%%\n")
    second = {**RECORD, "id": "2", "pids": {"doi": {"identifier": "10.5281/zenodo.2"}}}

    result = runner.invoke(app, ["convert"], input=json.dumps([RECORD, second]))

    assert result.exit_code == 0
    assert "\n%%\n" in result.stdout
