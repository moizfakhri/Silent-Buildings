import math

from nycdistress.metrics import average_precision, precision_at_k, roc_auc

Y = [0, 0, 1, 1]
S = [0.1, 0.4, 0.35, 0.8]  # the standard scikit-learn documentation example


def test_known_values():
    assert math.isclose(roc_auc(Y, S), 0.75)
    assert math.isclose(average_precision(Y, S), 0.8333333333333333)
    assert precision_at_k(Y, S, 2) == 0.5


def test_perfect_and_worst_and_ties():
    assert roc_auc([0, 1], [0, 1]) == 1.0 and roc_auc([0, 1], [1, 0]) == 0.0
    assert roc_auc([0, 1], [1, 1]) == 0.5                      # all tied
    assert roc_auc([0, 0, 1, 1], [1, 1, 1, 1]) == 0.5
    assert average_precision([0, 1], [1, 1]) == 0.5            # one tie group: precision = base rate
    assert average_precision([1, 1, 0, 0], [4, 3, 2, 1]) == 1.0


def test_single_class_is_nan():
    assert math.isnan(roc_auc([0, 0], [1, 2])) and math.isnan(average_precision([0, 0], [1, 2]))
