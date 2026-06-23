import pytest
from app.services.battery import decide_action


@pytest.mark.parametrize(
    "energy_price, average_radiation, expected",
    [
        # Ideal CHARGE scenario: low price + high radiation
        (49, 401, "CHARGE"),
        (0, 500, "CHARGE"),
        (30, 800, "CHARGE"),
        # Boundary edges of CHARGE rule: equality fails (rule uses strict > and <)
        (50, 401, "HOLD"),      # price == 50 (not < 50)
        (49, 400, "HOLD"),      # radiation == 400 (not > 400)
        (50, 400, "HOLD"),      # both at boundaries
        # Ideal DISCHARGE scenario: high price
        (151, 100, "DISCHARGE"),
        (300, 0, "DISCHARGE"),
        # Boundary edge of DISCHARGE rule
        (150, 500, "HOLD"),     # price == 150 (not > 150)
        # HOLD scenario: medium prices and medium radiation
        (100, 200, "HOLD"),
        (75, 350, "HOLD"),
        # High price but low radiation: still DISCHARGE (rule only looks at price)
        (200, 50, "DISCHARGE"),
    ],
)
def test_decide_action(energy_price, average_radiation, expected):
    assert decide_action(energy_price, average_radiation) == expected


def test_decide_action_returns_only_valid_actions():
    """Ensures the function never returns a value outside {CHARGE, DISCHARGE, HOLD}."""
    valid_actions = {"CHARGE", "DISCHARGE", "HOLD"}
    for price in [0, 49, 50, 150, 151, 200]:
        for radiation in [0, 400, 401, 800]:
            result = decide_action(price, radiation)
            assert result in valid_actions, (
                f"Invalid action '{result}' for price={price}, radiation={radiation}"
            )
