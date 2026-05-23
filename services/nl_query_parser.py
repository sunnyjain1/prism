import calendar
import re
from datetime import date, timedelta
from typing import Callable, Optional


class NLQueryParser:
    MONTHS = {
        "january": 1,
        "february": 2,
        "march": 3,
        "april": 4,
        "may": 5,
        "june": 6,
        "july": 7,
        "august": 8,
        "september": 9,
        "october": 10,
        "november": 11,
        "december": 12,
        "jan": 1,
        "feb": 2,
        "mar": 3,
        "apr": 4,
        "jun": 6,
        "jul": 7,
        "aug": 8,
        "sep": 9,
        "sept": 9,
        "oct": 10,
        "nov": 11,
        "dec": 12,
    }
    MONTH_PATTERN = "|".join(sorted(MONTHS.keys(), key=len, reverse=True))
    NUMBER_PATTERN = r"(?:₹|rs\.?|inr|\$)?\s*(\d[\d,]*(?:\.\d+)?)"
    STOPWORDS = {
        "a",
        "all",
        "an",
        "and",
        "at",
        "avg",
        "average",
        "biggest",
        "count",
        "did",
        "do",
        "does",
        "earned",
        "expense",
        "expenses",
        "find",
        "for",
        "from",
        "given",
        "highest",
        "how",
        "i",
        "income",
        "incomes",
        "is",
        "largest",
        "latest",
        "list",
        "many",
        "me",
        "money",
        "my",
        "of",
        "often",
        "on",
        "ordered",
        "orders",
        "paid",
        "received",
        "recent",
        "show",
        "smallest",
        "spend",
        "spending",
        "spent",
        "sum",
        "than",
        "the",
        "times",
        "to",
        "total",
        "transaction",
        "transactions",
        "what",
        "whats",
    }
    REMOVE_PATTERNS = [
        r"\bhow much(?: did)?(?: i)?\b",
        r"\bhow many(?: times)?(?: did)?(?: i)?\b",
        r"\bhow often(?: did)?(?: i)?\b",
        r"\bwhat(?:'s| is)\b",
        r"\bshow me\b",
        r"\bshow\b",
        r"\bfind\b",
        r"\bcount(?: of)?\b",
        r"\baverage\b",
        r"\bavg\b",
        r"\bmean\b",
        r"\btotal\b",
        r"\bsum\b",
        r"\bbiggest\b",
        r"\blargest\b",
        r"\bhighest\b",
        r"\bsmallest\b",
        r"\blowest\b",
        r"\brecent\b",
        r"\blatest\b",
        r"\boldest\b",
        r"\bearliest\b",
        r"\btransactions?\b",
        r"\borders?\b",
        r"\bexpenses?\b",
        r"\bincomes?\b",
        r"\bspending\b",
        r"\bspent\b",
        r"\bspend\b",
        r"\bearned\b",
        r"\bearn\b",
        r"\breceived\b",
        r"\breceive\b",
        r"\bpaid\b",
        r"\bpay\b",
        r"\bgiven\b",
        r"\bgive\b",
        r"\bmoney\b",
        r"\bthis week\b",
        r"\blast week\b",
        r"\bthis month\b",
        r"\blast month\b",
        r"\bthis year\b",
        r"\blast year\b",
        r"\btoday\b",
        r"\byesterday\b",
        rf"\b(?:in\s+)?(?:{MONTH_PATTERN})(?:\s+\d{{4}})?\b",
        r"\b(?:19|20)\d{2}\b",
        rf"\bbetween\s+{NUMBER_PATTERN}\s+(?:and|to)\s+{NUMBER_PATTERN}\b",
        rf"\b(?:above|over|more than|greater than|at least)\s+{NUMBER_PATTERN}\b",
        rf"\b(?:below|under|less than|at most|up to)\s+{NUMBER_PATTERN}\b",
    ]

    def __init__(self, today_provider: Optional[Callable[[], date]] = None):
        self.today_provider = today_provider or date.today

    def _today(self) -> date:
        return self.today_provider()

    @staticmethod
    def _normalize_whitespace(text: str) -> str:
        return re.sub(r"\s+", " ", text).strip()

    @staticmethod
    def _number_from_match(raw_value: str) -> float:
        cleaned = raw_value.replace(",", "").replace(" ", "")
        return float(cleaned)

    @staticmethod
    def _iso(value: date) -> str:
        return value.isoformat()

    def resolve_time_period(self, text: str) -> tuple[Optional[str], Optional[str]]:
        lowered = text.lower()
        today = self._today()

        if re.search(r"\btoday\b", lowered):
            return self._iso(today), self._iso(today)

        if re.search(r"\byesterday\b", lowered):
            yesterday = today - timedelta(days=1)
            return self._iso(yesterday), self._iso(yesterday)

        if re.search(r"\bthis week\b", lowered):
            start = today - timedelta(days=today.weekday())
            return self._iso(start), self._iso(today)

        if re.search(r"\blast week\b", lowered):
            end = today - timedelta(days=today.weekday() + 1)
            start = end - timedelta(days=6)
            return self._iso(start), self._iso(end)

        if re.search(r"\bthis month\b", lowered):
            start = today.replace(day=1)
            return self._iso(start), self._iso(today)

        if re.search(r"\blast month\b", lowered):
            this_month_start = today.replace(day=1)
            last_month_end = this_month_start - timedelta(days=1)
            start = last_month_end.replace(day=1)
            return self._iso(start), self._iso(last_month_end)

        if re.search(r"\bthis year\b", lowered):
            start = date(today.year, 1, 1)
            return self._iso(start), self._iso(today)

        if re.search(r"\blast year\b", lowered):
            year = today.year - 1
            return self._iso(date(year, 1, 1)), self._iso(date(year, 12, 31))

        month_match = re.search(rf"\b(?:in\s+)?({self.MONTH_PATTERN})(?:\s+(\d{{4}}))?\b", lowered)
        if month_match:
            month = self.MONTHS[month_match.group(1)]
            year = int(month_match.group(2) or today.year)
            last_day = calendar.monthrange(year, month)[1]
            return self._iso(date(year, month, 1)), self._iso(date(year, month, last_day))

        year_match = re.search(r"\b((?:19|20)\d{2})\b", lowered)
        if year_match:
            year = int(year_match.group(1))
            return self._iso(date(year, 1, 1)), self._iso(date(year, 12, 31))

        return None, None

    @staticmethod
    def _detect_aggregate(text: str) -> Optional[str]:
        if re.search(r"\b(how many|how often|times|count)\b", text):
            return "count"
        if re.search(r"\b(average|avg|mean)\b", text):
            return "average"
        if re.search(r"\b(how much|total|sum|spending)\b", text):
            return "sum"
        if re.search(r"\bmoney\b.*\b(given|paid|spent|received)\b|\b(given|paid|spent|received)\b.*\bmoney\b", text):
            return "sum"
        return None

    @staticmethod
    def _detect_sort(text: str) -> Optional[str]:
        if re.search(r"\b(biggest|largest|highest|max(?:imum)?)\b", text):
            return "amount_desc"
        if re.search(r"\b(smallest|lowest|min(?:imum)?)\b", text):
            return "amount_asc"
        if re.search(r"\b(oldest|earliest)\b", text):
            return "date_asc"
        if re.search(r"\b(recent|latest|newest)\b", text):
            return "date_desc"
        return None

    @staticmethod
    def _detect_type(text: str) -> Optional[str]:
        if re.search(r"\b(transfer|transferred|move|moved)\b", text):
            return "transfer"
        if re.search(r"\b(income|earned|earn|received|receive|salary|credited)\b", text):
            return "income"
        if re.search(r"\b(expense|expenses|spent|spend|spending|paid|pay|given|give|ordered|order)\b", text):
            return "expense"
        return None

    def _extract_amount_filters(self, text: str) -> tuple[Optional[float], Optional[float]]:
        between_match = re.search(
            rf"\bbetween\s+{self.NUMBER_PATTERN}\s+(?:and|to)\s+{self.NUMBER_PATTERN}\b",
            text,
        )
        if between_match:
            first = self._number_from_match(between_match.group(1))
            second = self._number_from_match(between_match.group(2))
            return min(first, second), max(first, second)

        minimum_match = re.search(
            rf"\b(?:above|over|more than|greater than|at least)\s+{self.NUMBER_PATTERN}\b",
            text,
        )
        maximum_match = re.search(
            rf"\b(?:below|under|less than|at most|up to)\s+{self.NUMBER_PATTERN}\b",
            text,
        )

        min_amount = self._number_from_match(minimum_match.group(1)) if minimum_match else None
        max_amount = self._number_from_match(maximum_match.group(1)) if maximum_match else None
        return min_amount, max_amount

    def _extract_search_term(self, query: str) -> Optional[str]:
        cleaned = query
        for pattern in self.REMOVE_PATTERNS:
            cleaned = re.sub(pattern, " ", cleaned, flags=re.IGNORECASE)

        cleaned = re.sub(r"[^\w\s&'-]", " ", cleaned)
        tokens = []
        for token in cleaned.split():
            normalized = token.lower().strip("'-")
            if not normalized or normalized in self.STOPWORDS:
                continue
            tokens.append(token.strip())

        search = self._normalize_whitespace(" ".join(tokens))
        return search or None

    def build_interpretation(self, parsed_query: dict) -> str:
        aggregate = parsed_query.get("aggregate") or "list"
        transaction_type = parsed_query.get("type")
        search = parsed_query.get("search")
        date_from = parsed_query.get("date_from")
        date_to = parsed_query.get("date_to")
        min_amount = parsed_query.get("min_amount")
        max_amount = parsed_query.get("max_amount")
        sort_by = parsed_query.get("sort_by")

        if aggregate == "sum":
            lead = {
                "expense": "total expenses",
                "income": "total income",
                "transfer": "total transfers",
            }.get(transaction_type, "total amount")
        elif aggregate == "count":
            lead = {
                "expense": "expense transactions count",
                "income": "income transactions count",
                "transfer": "transfer count",
            }.get(transaction_type, "transaction count")
        elif aggregate == "average":
            lead = {
                "expense": "average expense",
                "income": "average income",
                "transfer": "average transfer",
            }.get(transaction_type, "average amount")
        elif sort_by == "amount_desc":
            lead = {
                "expense": "biggest expenses",
                "income": "largest income entries",
                "transfer": "largest transfers",
            }.get(transaction_type, "largest transactions")
        elif sort_by == "amount_asc":
            lead = {
                "expense": "smallest expenses",
                "income": "smallest income entries",
                "transfer": "smallest transfers",
            }.get(transaction_type, "smallest transactions")
        else:
            lead = {
                "expense": "expenses",
                "income": "income",
                "transfer": "transfers",
            }.get(transaction_type, "transactions")

        details = [lead]
        if search:
            details.append(f"matching '{search}'")
        if date_from and date_to:
            if date_from == date_to:
                details.append(f"on {date_from}")
            else:
                details.append(f"from {date_from} to {date_to}")
        if min_amount is not None and max_amount is not None:
            details.append(f"between {min_amount:g} and {max_amount:g}")
        elif min_amount is not None:
            details.append(f"above {min_amount:g}")
        elif max_amount is not None:
            details.append(f"below {max_amount:g}")

        return f"Showing {' '.join(details)}"

    def parse(self, query: str) -> dict:
        normalized_query = self._normalize_whitespace(query)
        lowered = normalized_query.lower()

        aggregate = self._detect_aggregate(lowered)
        sort_by = self._detect_sort(lowered)
        transaction_type = self._detect_type(lowered)
        date_from, date_to = self.resolve_time_period(lowered)
        min_amount, max_amount = self._extract_amount_filters(lowered)
        search = self._extract_search_term(normalized_query)

        matched_rule = any(
            value is not None
            for value in [aggregate, sort_by, transaction_type, date_from, date_to, min_amount, max_amount]
        )
        if search and search.lower() != lowered:
            matched_rule = True

        if not matched_rule and not search:
            search = normalized_query or None

        return {
            "search": search,
            "type": transaction_type,
            "date_from": date_from,
            "date_to": date_to,
            "min_amount": min_amount,
            "max_amount": max_amount,
            "categories": [],
            "aggregate": aggregate or "list",
            "sort_by": sort_by or "date_desc",
            "original_query": normalized_query,
            "parsed": matched_rule,
        }
