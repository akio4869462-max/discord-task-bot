import random

import fortune_logic as fl


def test_draw_fortune_is_deterministic_with_seeded_rng():
    rng = random.Random(42)
    first = fl.draw_fortune(rng=rng)
    rng2 = random.Random(42)
    second = fl.draw_fortune(rng=rng2)
    assert first == second


def test_draw_fortune_returns_known_rank():
    fortune = fl.draw_fortune(rng=random.Random(1))
    ranks = [f["rank"] for f in fl.FORTUNES]
    assert fortune["rank"] in ranks


def test_draw_fortune_gate_number_in_range():
    for seed in range(20):
        fortune = fl.draw_fortune(rng=random.Random(seed))
        assert 1 <= fortune["gate_number"] <= 18


def test_fortune_weights_are_positive_and_sum_reasonably():
    weights = [f["weight"] for f in fl.FORTUNES]
    assert all(w > 0 for w in weights)
    assert sum(weights) == 100


def test_all_ranks_are_unique():
    ranks = [f["rank"] for f in fl.FORTUNES]
    assert len(ranks) == len(set(ranks))


def test_format_fortune_message_includes_rank_and_name():
    fortune = fl.draw_fortune(rng=random.Random(7))
    text = fl.format_fortune_message(fortune, "あきお")
    assert "あきお" in text
    assert fortune["rank"] in text
    assert fortune["message"] in text
    assert str(fortune["gate_number"]) in text


def test_draw_fortune_over_many_trials_hits_every_rank():
    rng = random.Random(123)
    seen = set()
    for _ in range(500):
        seen.add(fl.draw_fortune(rng=rng)["rank"])
    assert seen == {f["rank"] for f in fl.FORTUNES}
