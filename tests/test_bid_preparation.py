from copy import deepcopy

import pytest

from bidkit.__main__ import main
from bidkit.audit import load_audit
from bidkit.bid_preparation import prepare
from bidkit.data_store import read_json, write_json
from bidkit.project_schema import load_analysis


def inputs(config):
    a = load_analysis(config)
    form = {"schema_version": 1, "project_id": config.id, "form_status": "TEST_ONLY_NOT_OFFICIAL", "current_official_form_verified": False, "sources": a["quantities"][0]["sources"], "lines": [{"id": "1", "description": "TEST form line", "scope": "base", "quantity_ids": ["Q1"], "mapping_status": "PROVISIONAL", "sources": a["quantities"][0]["sources"]}], "totals": [{"id": "TEST TOTAL", "line_ids": ["1"]}], "pending_decisions": []}
    return a, load_audit(config), form


def test_bid_draft_never_claims_authorization_or_unsupported_amount(project_factory):
    c = project_factory();a, manifest, form = inputs(c)
    r = prepare(a, manifest, form)
    assert r["lines"][0]["proposed_amount"] is None and r["totals"][0]["amount"] is None
    assert r["mapping"][0]["official_line_id"] == "1"
    assert r["authorization"]["signed"] is False and r["authorization"]["submitted"] is False
    assert all(r["status"] != "APPROVED" and not r["signed"] for r in r["checklist"])


@pytest.mark.parametrize("case", ["foreign_project", "cross_scope", "duplicate_allocation", "unknown_item"])
def test_bid_mapping_cannot_mix_or_double_count_items(project_factory, case):
    c = project_factory();a, manifest, form = inputs(c)
    if case == "foreign_project": form["project_id"] = "other"
    if case == "cross_scope": form["lines"][0]["scope"] = "alternate_1"
    if case == "duplicate_allocation":
        another = deepcopy(form["lines"][0]);another["id"] = "2";form["lines"].append(another)
    if case == "unknown_item": form["lines"][0]["quantity_ids"] = ["INVENTED"]
    with pytest.raises(ValueError): prepare(a, manifest, form)


def test_missing_form_has_no_invented_rows_and_keeps_estimate_items(project_factory):
    c = project_factory();a, manifest, form = inputs(c)
    form["lines"] = [];form["totals"] = []
    r = prepare(a, manifest, form)
    assert not r["lines"] and len(r["mapping"]) == 1
    assert r["mapping"][0]["official_line_id"] is None


def test_duplicate_descriptions_are_retained_for_clarification(project_factory):
    c = project_factory();a, manifest, form = inputs(c)
    row = deepcopy(form["lines"][0]);row.update(id="2", quantity_ids=[])
    form["lines"].append(row)
    r = prepare(a, manifest, form)
    assert len(r["lines"]) == 2
    assert r["pending_decisions"][0]["issue"] == "DUPLICATE_FORM_DESCRIPTION_REQUIRES_CLARIFICATION"


def test_bid_package_build_and_stale_mapping_detection(project_factory):
    c = project_factory();a, manifest, form = inputs(c)
    write_json(c.project_dir/"bid_form.json", form)
    assert main(["cost-init", "--root", str(c.root), "--project", c.id]) == 0
    assert main(["build", "--root", str(c.root), "--project", c.id]) == 0
    assert (c.output_dir/"bid-preparation/Internal_Bid_Package_DRAFT.xlsx").exists()
    form["pending_decisions"] = ["New clarification"]
    write_json(c.project_dir/"bid_form.json", form)
    assert main(["validate", "--root", str(c.root), "--project", c.id]) == 1


def test_form_specific_requirements_keep_evidence_and_pending_status(project_factory):
    c = project_factory();a, manifest, form = inputs(c)
    form["additional_requirements"] = [{"id": "FORM-BOND", "requirement": "TEST ONLY bond requirement", "phase": "bid", "sources": form["sources"]}]
    r = prepare(a, manifest, form)
    bond = next(row for row in r["checklist"] if row["id"] == "FORM-BOND")
    assert bond["sources"] == form["sources"] and bond["status"] == "PENDING_CONTRACTOR_EVIDENCE"
    assert not bond["signed"] and not bond["submitted"]
    form["additional_requirements"][0]["sources"] = []
    with pytest.raises(ValueError): prepare(a, manifest, form)


def test_form_specific_requirement_rejects_false_page_reference(project_factory):
    c = project_factory();a, manifest, form = inputs(c)
    wrong = deepcopy(form["sources"]);wrong[0]["page"] = 99999
    form["additional_requirements"] = [{"id": "FORM-BOND", "requirement": "TEST ONLY", "phase": "bid", "sources": wrong}]
    write_json(c.project_dir/"bid_form.json", form)
    with pytest.raises(SystemExit) as error:
        main(["build", "--root", str(c.root), "--project", c.id])
    assert error.value.code == 2
