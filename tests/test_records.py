from bidkit.records import AMENDMENTS, TAKEOFF


def test_final_bid_addendum_is_04() -> None:
    final = [item for item in AMENDMENTS if item["precedence"] == "active_final_for_bid_time"]
    assert len(final) == 1
    assert final[0]["addendum"] == "04"


def test_takeoff_has_no_invented_pending_quantities() -> None:
    assert all(item["quantity"] is None for item in TAKEOFF if item["quantity_status"] == "PENDIENTE DE MEDICIÓN")
