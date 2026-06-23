import pytest
from app.services.battery import decide_action


@pytest.mark.parametrize(
    "energy_price, average_radiation, expected",
    [
        # Cenário ideal CHARGE: preço baixo + muita radiação
        (49, 401, "CHARGE"),
        (0, 500, "CHARGE"),
        (30, 800, "CHARGE"),
        # Bordas da regra CHARGE: equality falha (regra usa > e < exclusivo)
        (50, 401, "HOLD"),      # price == 50 (não < 50)
        (49, 400, "HOLD"),      # radiation == 400 (não > 400)
        (50, 400, "HOLD"),      # ambos nos limites
        # Cenário ideal DISCHARGE: preço alto
        (151, 100, "DISCHARGE"),
        (300, 0, "DISCHARGE"),
        # Borda da regra DISCHARGE
        (150, 500, "HOLD"),     # price == 150 (não > 150)
        # Cenário HOLD: preços médios e radiação média
        (100, 200, "HOLD"),
        (75, 350, "HOLD"),
        # Preço alto mas radiação baixa: ainda DISCHARGE (regra só olha preço)
        (200, 50, "DISCHARGE"),
    ],
)
def test_decide_action(energy_price, average_radiation, expected):
    assert decide_action(energy_price, average_radiation) == expected


def test_decide_action_returns_only_valid_actions():
    """Garante que a função nunca retorna um valor fora do conjunto {CHARGE, DISCHARGE, HOLD}."""
    valid_actions = {"CHARGE", "DISCHARGE", "HOLD"}
    for price in [0, 49, 50, 150, 151, 200]:
        for radiation in [0, 400, 401, 800]:
            result = decide_action(price, radiation)
            assert result in valid_actions, (
                f"Ação inválida '{result}' para price={price}, radiation={radiation}"
            )
