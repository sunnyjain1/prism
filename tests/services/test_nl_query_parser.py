from datetime import date

from services.nl_query_parser import NLQueryParser


TODAY = date(2025, 2, 14)


def build_parser() -> NLQueryParser:
    return NLQueryParser(today_provider=lambda: TODAY)


def test_parse_spend_query_with_entity_and_sum_aggregate():
    result = build_parser().parse("how much did I spend on petrol")

    assert result == {
        "search": "petrol",
        "type": "expense",
        "date_from": None,
        "date_to": None,
        "min_amount": None,
        "max_amount": None,
        "categories": [],
        "aggregate": "sum",
        "sort_by": "date_desc",
        "original_query": "how much did I spend on petrol",
        "parsed": True,
    }


def test_parse_count_query_and_entity_extraction():
    result = build_parser().parse("how many times I ordered from swiggy")

    assert result["search"] == "swiggy"
    assert result["aggregate"] == "count"
    assert result["type"] == "expense"
    assert result["parsed"] is True


def test_parse_date_filters_for_named_month_and_year():
    result = build_parser().parse("expenses in January 2025")

    assert result["type"] == "expense"
    assert result["date_from"] == "2025-01-01"
    assert result["date_to"] == "2025-01-31"
    assert result["search"] is None


def test_parse_amount_filters():
    result = build_parser().parse("transactions above 5,000")

    assert result["min_amount"] == 5000
    assert result["max_amount"] is None
    assert result["search"] is None


def test_resolve_relative_periods():
    parser = build_parser()

    assert parser.resolve_time_period("income last month") == ("2025-01-01", "2025-01-31")
    assert parser.resolve_time_period("total spending this week") == ("2025-02-10", "2025-02-14")
    assert parser.resolve_time_period("salary last year") == ("2024-01-01", "2024-12-31")


def test_parse_biggest_expense_query_sets_sorting():
    result = build_parser().parse("What's my biggest expense?")

    assert result["type"] == "expense"
    assert result["sort_by"] == "amount_desc"
    assert result["aggregate"] == "list"
    assert result["parsed"] is True
