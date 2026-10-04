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


def test_a_range_written_at_two_scales_settles_nothing_and_is_not_compared_across_them():
    """"150.000 - 400.000" is a hundred and fifty thousand on one form and a hundred and fifty
    on another, and the text does not say which.

    This mattered twice. A corrected value written the same way asks the range beside it which
    scale it is on — and the range was read by the same rule it was being asked to correct, so
    the two agreed while both were a thousand out, and no check could see it: the small value sat
    inside its own small range. And where the value was read correctly and the range was not, the
    value was reported as outside a range it was never compared with.
    """
    from epicrisis import reference
    from epicrisis.printed_values import number_as_printed

    # The range is still read — a urine specific gravity has to keep its band.
    assert reference.parse("1.005 - 1.030") == (1.005, 1.03)
    # But it settles nothing about another number written the same way.
    assert number_as_printed({"value_as_printed": "250.000", "reference_as_printed": "150.000 - 400.000"}) is None
    assert number_as_printed({"value_as_printed": "1.234", "reference_as_printed": "800 - 1500"}) == 1234.0
    # And a value a thousand away from such a range is not reported against it.
    assert reference.outside(250000.0, "150.000 - 400.000") is None
    assert reference.outside(1.045, "1.005 - 1.030") is True

    # A range shape must not begin part-way through a group of digits: this used to match
    # "000 - 400" and hand back a platelet range starting at nought. It is read whole instead —
    # a space groups thousands and is never a decimal point, so unlike the dot and the comma this
    # shape holds no question at all, and refusing it cost a platelet range its band for nothing.
    assert reference.parse("150 000 - 400 000") == (150000.0, 400000.0)
    assert reference.reads_two_ways("150 000 - 400 000") is False


def test_every_way_a_form_says_less_than_is_known_to_both_halves_of_the_program():
    """There were two lists of direction words in two files and they had already drifted.

    "menos de" was a comparator to one and not to the other, so every Spanish value written that
    way was reported as carrying a comparator its form had not printed. And no Greek word was in
    the range reader at all, so a Greek one-sided range drew no band and was compared with
    nothing — including "έως", which failed to match itself once casefold had turned its final
    sigma into a medial one.
    """
    from epicrisis import reference
    from epicrisis.printed_values import comparator_printed

    below = ("менее 5", "не выше 5", "не більше 5", "hasta 5", "menor de 5", "menos de 5",
             "inferior a 5", "έως 5", "μέχρι 5", "κάτω από 5", "μικρότερο από 5", "< 5", "≤ 5")  # fmt: skip
    above = ("более 5", "понад 5", "más de 5", "mayor de 5", "superior a 5", "άνω του 5", "> 5")

    for text in below:
        assert reference.parse(text) == (None, 5.0), text
        assert comparator_printed(text), text
    for text in above:
        assert reference.parse(text) == (5.0, None), text
        assert comparator_printed(text), text

    # A printed range is not a comparator, and must not be read as one.
    for text in ("3,5 - 5,5", "12 - 16"):
        assert not comparator_printed(text) and reference.parse(text)


def test_a_word_of_direction_behind_its_number_is_one_to_both_halves_too():
    """The half of that list the reader of values could not match, in all five languages at once.

    The comment over the list says a form prints "до 5" as readily as "5 и более", and names the
    English "20 or less" as a shape printed by the thousand. The reader was anchored to the start
    of the string, so not one word standing behind its number was ever a comparator to it — while
    reference.parse, reading a word "wherever it stands", read every one of these correctly. Each
    such value was handed `comparator_not_printed` with its comparator read exactly right, and the
    document went to "to check" for it.
    """
    from epicrisis import reference
    from epicrisis.printed_values import comparator_printed, unexplained_letters

    below = ("20 or less", "20 или менее", "5 або менше", "5 o menos", "5 ή λιγότερο", "5 Ή ΛΙΓΟΤΕΡΟ")
    above = ("18 и более", "5 і більше", "40 and above", "5 o más", "5 ή περισσότερο")

    for text in below:
        assert comparator_printed(text), text
        assert not unexplained_letters(text), text
    for text in above:
        assert comparator_printed(text), text
        assert not unexplained_letters(text), text
    # Both halves of the list on one number, which is how "от 5 до 10" is printed, and the two
    # readers must still agree that something was printed.
    assert comparator_printed("от 5 до 10") and reference.parse("от 5 до 10") == (5.0, 10.0)

    # And what stands behind a number and is not a direction: a unit, and the two words of the
    # list that head a column and are a time behind a number.
    for text in ("5 mg", "120 мин", "120 min", "5 max", "3,5 - 5,5", "5"):
        assert not comparator_printed(text), text


def test_a_sign_beside_the_number_outranks_a_word_further_along():
    """"≤75% від білірубіну загального" was read as a floor of seventy-five, not a ceiling.

    "від" — "from" — is a word of direction in Ukrainian, and it stood four characters after the
    sign in an ordinary sentence about what the seventy-five per cent was of. Words were looked
    for anywhere in the text and before the signs were looked at at all, so the band came out
    upside down and the value was judged against it the wrong way round.
    """
    from epicrisis.reference import parse

    assert parse("≤75 мкмоль/л") == (None, 75.0)
    assert parse("≤75 від верхньої межі") == (None, 75.0)
    assert parse("> 3 до вечері") == (3.0, None)
    # A word before the number still says the direction, which is where a form prints it.
    assert parse("до 10 в полі зору") == (None, 10.0)
    assert parse("от 3") == (3.0, None)
    assert parse("hasta 200") == (None, 200.0)
    assert parse("más de 30") == (30.0, None)


def test_a_table_of_what_a_result_would_mean_is_not_a_range():
    """Three bands with their names, printed where a range goes, and the middle one was taken.

    "< 20.0 Normal / 20.0 - 52.0 Suspicious / > 52.0 Elevated" was read as a reference range of
    twenty to fifty-two — which is the *suspicious* band. A value inside it was then held to be
    inside its printed range, and a value below twenty, which the form calls normal, was held to
    be under the range. Two ranges separated by a semicolon were already refused; separated by a
    word, they were not.
    """
    from epicrisis.reference import parse

    assert parse("< 20.0 Normal\n20.0 - 52.0 Suspicious\n> 52.0 Elevated") is None
    assert parse("<5.2 відсутність ризику 5.2-6.2 умовний ризик >6.2 високий ризик") is None
    assert parse("< 20 Φυσιολογική, 20 - 200 Μικροαλβουμινουρία") is None
    # An ordinary range, with anything a laboratory likes printed around it, is still a range.
    assert parse("( 10.0 - 18.0 )") == (10.0, 18.0)
    assert parse("3,0-8,0 ммоль/л") == (3.0, 8.0)
    # And a label of its own in front of it. This line used to read
    #     parse("Норма: 0,55 - 1,02") == (0.55, 1.02) or parse("0,55 - 1,02") == (0.55, 1.02)
    # whose second half is the line above it and is always true, so the line could not fail — and
    # its first half was false: every range printed under a label lost its band, because the guard
    # against titers and against one range for men and another for women was the colon itself.
    assert parse("Норма: 0,55 - 1,02") == (0.55, 1.02)
    assert parse("Норма до: 20") == (None, 20.0)  # the direction printed inside the label
    # What that guard was for is still refused: a ratio, and two bands printed side by side.
    assert parse("1:40") is None and parse("Титр 1:160") is None
    assert parse("М: <5 Ж: <7") is None
    assert parse("< 20 Норма: 20 - 200 микроальбуминурия") is None


def test_a_share_of_another_measurement_is_not_a_range_of_this_one():
    """"≤75% від білірубіну загального" is a real limit and a person can read it.

    It is not a range in the unit of the value beside it: seventy-five per cent of another number
    on the same form. Drawn as a band on that value's own chart it is simply wrong — seventy-five,
    in micromoles, over values between five and twenty-five — and compared with, it compares the
    value against a number belonging to something else.
    """
    from epicrisis.reference import parse

    assert parse("≤75% від білірубіну загального") is None
    assert parse("< 30% of total") is None
    # A per-cent range that is a range of this value is untouched.
    assert parse("0,2-1,0%") == (0.2, 1.0)
    assert parse("19,0-37,0%") == (19.0, 37.0)


def test_a_unit_printed_in_front_of_a_range_is_not_another_range():
    """"х10⁹/л 4,0-9,0" — a white cell count with its unit first, and a band that vanished.

    Refusing a range with a number before it was meant for a table of interpretations printed in
    place of one. A unit carrying a power has numbers in it, so the refusal took the band off
    every form that prints its unit first and told the comparison nothing at all — a loss no
    count of findings shows, because a finding that is never made is not counted anywhere.
    """
    from epicrisis.reference import parse

    assert parse("х10^9/л 4,0-9,0") == (4.0, 9.0)
    assert parse("10⁹/л 4,0-9,0") == (4.0, 9.0)
    assert parse("x10^3/µL 150 - 400") == (150.0, 400.0)
    # And a range already stated before this one is still refused: that is a sign and its number.
    assert parse("< 20 Normal, 20 - 200 High") is None


def test_a_word_of_direction_is_read_wherever_the_form_prints_it():
    """Russian and Ukrainian put it after the number as readily as before, and so does English."""
    from epicrisis.reference import parse

    assert parse("18 и более") == (18.0, None)
    assert parse("5 і більше") == (5.0, None)
    assert parse("40 and above") == (40.0, None)
    assert parse("до 10 в полі зору") == (None, 10.0)


def test_the_longer_phrase_decides_which_way_a_range_is_open():
    """"не менее 18" is at least eighteen, and it holds the word "менее", which is less than.

    Read by whichever word was looked for first, a floor became a ceiling and the band was drawn
    upside down — with the value then judged against it the wrong way round.
    """
    from epicrisis.reference import parse

    assert parse("не менее 18") == (18.0, None)
    assert parse("не ниже 3") == (3.0, None)
    assert parse("не менше 4") == (4.0, None)
    assert parse("не более 7") == (None, 7.0)
    assert parse("не выше 9") == (None, 9.0)
    assert parse("не більше 6") == (None, 6.0)
    # And the plain words still say what they say.
    assert parse("менее 10") == (None, 10.0) and parse("более 2") == (2.0, None)
