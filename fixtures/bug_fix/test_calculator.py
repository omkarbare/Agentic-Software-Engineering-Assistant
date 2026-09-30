import pytest

from calculator import divide


def test_divide_by_zero_is_explicit() -> None:
    with pytest.raises(ZeroDivisionError):
        divide(1, 0)


def test_division_preserves_fractional_result() -> None:
    assert divide(3, 2) == 1.5
