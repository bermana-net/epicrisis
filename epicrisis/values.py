"""What a value is on the form it came from, and which values a series is made of.

A laboratory form prints more than its own results. Beside the result of the day it prints the
previous one, a target, a column headed "before" — numbers that belong to another day or to
nobody. They are transcribed, because they are on the page, and they are listed in the card,
because a person looking at the document should see what the document says. They are not points
on a line: drawn as one, a previous result lands on the date of the form that quoted it, which is
a date no laboratory ever gave it.

Which of them counts as a result was decided in twelve places — four strings of SQL in the
queries, one in the indicators, one in the suspects, and conditions in Python in validation, in
the document pages and in the charts. Changing the rule meant finding all twelve, and the day it
changed for the charts the other eleven did not hear about it.

It is decided here now. The SQL sites take the fragment, the Python sites take the question.
"""

RESULT = "result"


def is_result(item) -> bool:
    """Whether this value is the result of the form it stands on, rather than something beside it.

    A value with no role recorded is a result: rows written before roles existed are the form's
    own numbers, and reading them as anything else would empty every old series in the archive.
    """
    role = item.get("value_role") if hasattr(item, "get") else getattr(item, "value_role", None)
    return (role or RESULT) == RESULT


def only_results(table: str = "o") -> str:
    """The condition that keeps a query to the results of the forms it reads.

    `table` is the alias the query gives the observations, because the queries differ in that and
    in nothing else.
    """
    return f"{table + '.' if table else ''}value_role = '{RESULT}'"
