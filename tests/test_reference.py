"""Reading printed ranges. Synthetic strings only."""

from epicrisis.reference import outside, parse


def test_a_printed_range_is_read_only_when_it_is_plain():
    assert parse("3,89-5,84") == (3.89, 5.84)
    assert parse("53-115 мкмоль/л") == (53.0, 115.0)
    assert parse("< 46 Е/л") == (None, 46.0)
    assert parse("до 90 Е/л") == (None, 90.0)
    assert parse("> 1,7 ммоль/л") == (1.7, None)
    # Two ranges in one line, a word, nothing at all: not read rather than guessed.
    assert parse("ч - 24-195; ж - 24-170") is None
    assert parse("не виявлено") is None
    assert parse(None) is None


def test_a_value_is_compared_only_with_a_range_that_was_read():
    assert outside(6.9, "3,89-5,84") is True
    assert outside(4.2, "3,89-5,84") is False
    assert outside(120, "53-115 мкмоль/л") is True
    assert outside(50, "< 46 Е/л") is True
    assert outside(40, "< 46 Е/л") is False
    assert outside(7.0, "ч - 24-195; ж - 24-170") is None
    assert outside(None, "3,89-5,84") is None
    # A value printed as "less than" the low bound of its own range is a miss; inside it is not.
    assert outside(0.5, "0,5-1,0", comparator="<") is True


def test_a_range_is_what_a_form_printed_as_a_range():
    """Two numbers in a line are not a range, and the program acts on this over the network."""
    from epicrisis.reference import outside, parse

    # A unit that carries a number of its own, a titer, two limits for the two sexes: not ranges.
    assert parse("до 150 мг/24 ч") == (None, 150.0)
    assert outside(20.0, "до 150 мг/24 ч") is False
    assert parse("1:40") is None
    assert parse("М <5 Ж <7") is None
    assert parse("норма") is None

    # Printed backwards is a finding for a person, not something to sort quietly into place.
    assert parse("10-2") is None

    # And the ordinary shapes still read.
    assert parse("3,89-5,84") == (3.89, 5.84)
    assert parse("0.8 -1.2") == (0.8, 1.2)
    assert parse("0 - 5 в п/зр") == (0.0, 5.0)
    assert parse("< 5,2") == (None, 5.2)
    assert parse("менее 5") == (None, 5.0)
    assert parse("от 1,2") == (1.2, None)
