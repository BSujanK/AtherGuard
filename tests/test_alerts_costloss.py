"""Cost-loss arithmetic on hand-computable numbers."""
import pytest

from aetherguard.alerts import costloss as cl

RISK_POS = [1e-4, 5e-5, 2e-6, 1e-3]
RISK_NEG = [1e-6, 2e-5, 6e-5, 3e-7]
WEIGHT_NEG = [100.0, 100.0, 100.0, 700.0]      # total 1000


def test_alert_rate_is_the_weighted_share_of_negatives_at_or_above_the_threshold():
    assert cl.weighted_alert_rate(RISK_NEG, WEIGHT_NEG, 2e-5) == pytest.approx(0.2)
    assert cl.weighted_alert_rate(RISK_NEG, WEIGHT_NEG, 1.0) == 0.0
    assert cl.weighted_alert_rate(RISK_NEG, WEIGHT_NEG, 0.0) == 1.0


def test_operating_point_numbers():
    point = cl.operating_point(RISK_POS, RISK_NEG, WEIGHT_NEG, 2e-5, base_rate=1e-3)
    assert point["alerts_per_1000_cell_days"] == pytest.approx(200.0)
    assert point["recall"] == pytest.approx(0.75)
    assert point["implied_cost_ratio"] == 2e-5
    # expense = 2e-5 * 0.2 + 1e-3 * 0.25 ; reference min(base_rate, C/L) = 2e-5
    assert point["expense"] == pytest.approx(4e-6 + 2.5e-4)
    assert point["relative_expense"] == pytest.approx((4e-6 + 2.5e-4) / 2e-5)


def test_a_threshold_that_beats_both_reference_strategies_has_relative_expense_below_one():
    # cheap alerts (C/L = 1e-4 < base rate 1e-3), recall 1, alert rate 0.01
    point = cl.operating_point([1.0] * 5, [0.0] * 99 + [1.0], [1.0] * 100, 0.5, base_rate=1e-3, cost_ratio=1e-4)
    assert point["expense"] == pytest.approx(1e-4 * 0.01) and point["relative_expense"] < 1


def test_table_has_named_points_and_one_row_per_ratio_with_the_ratio_as_threshold():
    table = cl.cost_loss_table(RISK_POS, RISK_NEG, WEIGHT_NEG, 1e-3, {"watch": 1e-5, "warning": 4e-5},
                               [0.1, 0.02, 0.005])
    assert set(table["operating_points"]) == {"watch", "warning"}
    assert [r["cost_loss"] for r in table["ratios"]] == [0.1, 0.02, 0.005]
    assert [r["threshold"] for r in table["ratios"]] == [0.1, 0.02, 0.005]
    assert table["ratios"][0]["alerts_per_1000_cell_days"] == 0.0 and table["ratios"][0]["recall"] == 0.0
    assert table["operating_points"]["warning"]["implied_cost_ratio"] == 4e-5


@pytest.mark.parametrize("kwargs", [{"base_rate": 0.0}, {"base_rate": 1.0}])
def test_bad_base_rate_is_rejected(kwargs):
    with pytest.raises(ValueError, match="base_rate"):
        cl.operating_point(RISK_POS, RISK_NEG, WEIGHT_NEG, 1e-5, **kwargs)


def test_empty_positives_and_zero_weights_are_rejected():
    with pytest.raises(ValueError, match="positives"):
        cl.operating_point([], RISK_NEG, WEIGHT_NEG, 1e-5, 1e-3)
    with pytest.raises(ValueError, match="positive sum"):
        cl.weighted_alert_rate([1.0], [0.0], 0.5)
    with pytest.raises(ValueError, match="same length"):
        cl.weighted_alert_rate([1.0, 2.0], [1.0], 0.5)
