"""
User Import Profile Service.

Stores and applies per-user import configuration so that every bulk upload
produces transactions that look and feel like the user's existing entries.

Config schema (stored as JSON in user_import_profiles.config):

{
  "version": 1,

  // Ordered list of note-text → category rules.
  // Applied to the transaction's description (= Money Manager "Note" field).
  // First matching rule wins.
  //
  // These are used in two places:
  //   1. Bulk import  — exact/contains/startswith match on the imported note.
  //   2. Auto entries — word-boundary match on bank narrations (SMS, AA, Gmail),
  //      via resolve_category_id(). See match_note_rule() for the runtime matcher.
  "note_rules": [
    {
      "pattern":    "snacks",        // text to match
      "match":      "exact",         // "exact" | "contains" | "startswith"
      "category":   "Sukoon",        // Prism category name to assign
      "type":       "expense",       // "expense" | "income" — guards runtime matching
      "frequency":  1312,            // informational: how often seen in history
      "confidence": 1.0              // informational: % of time this mapping held
    }
  ],

  // Money Manager account name → Prism account metadata.
  "account_mappings": {
    "HDFC": { "name": "HDFC", "type": "savings" },
    "HDFC Card": { "name": "HDFC Card", "type": "credit_card" }
  },

  // Category name → category name. Two jobs:
  //   - renaming on import (identity by default: "Sukoon" -> "Sukoon")
  //   - explicit aliases from a built-in category name to the user's own,
  //     for equivalences no heuristic should decide ("Groceries" -> "Household")
  "category_mappings": {
    "Sukoon": "Sukoon",
    "Groceries": "Household"
  },

  // The user's own category names and how heavily each is used. Lets an
  // auto-created entry join an existing category ("Food") instead of forking a
  // near-duplicate ("Food & Dining"). See map_to_user_category().
  "category_vocabulary": {
    "Sukoon": { "count": 1456, "type": "expense" }
  },

  // Rows whose category matches one of these are dropped on import.
  "skip_categories": ["Modified Bal."],

  // Rows whose description (note) matches one of these are dropped on import.
  "skip_notes": ["difference", "loss"]
}
"""
from __future__ import annotations

import io
import logging
import re
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
from sqlalchemy.orm import Session

from models import Category, Transaction, UserImportProfile
from schemas import TransactionCreate, TransactionType
from services.import_entity_service import ImportEntityService

logger = logging.getLogger(__name__)

# A learned note rule must have been seen at least this many times, and have held
# this consistently, before it is trusted to categorize an *auto-created* entry.
# Bulk import is more permissive (see _extract_note_rules) because the user is
# reviewing a preview; auto entries land silently, so the bar is higher.
RUNTIME_MIN_FREQUENCY = 3
RUNTIME_MIN_CONFIDENCE = 0.80

# Words that carry no meaning inside a bank narration. A note rule whose pattern
# is made only of these can never identify a transaction.
NARRATION_NOISE = {
    "upi", "imps", "neft", "rtgs", "ach", "pos", "atm", "emi", "dr", "cr", "debit",
    "credit", "card", "bank", "payment", "paid", "pay", "transfer", "txn", "ref",
    "utr", "rrn", "auto", "mandate", "si", "ecs", "gst", "fees", "fee", "charge",
    "charges", "test", "misc", "other", "others", "amount", "amt", "bal", "balance",
    "to", "from", "for", "the", "and", "via", "at", "in", "on", "by", "of",
}


# ---------------------------------------------------------------------------
# Account-type heuristics: infer Prism AccountType from typical usage pattern.
# ---------------------------------------------------------------------------
_ACCOUNT_TYPE_HINTS: Dict[str, str] = {
    "hdfc rupay": "credit_card",
    "hdfc card": "credit_card",
    "icici card": "credit_card",
    "credit card": "credit_card",
    "card": "credit_card",
    "hdfc deposit": "savings",
    "fixed deposit": "savings",
    "fd": "savings",
    "deposit": "savings",
    "mutual fund": "investment",
    "mf": "investment",
    "gold": "investment",
    "stocks": "investment",
    "paytm": "checking",
    "amazon pay": "checking",
    "phonepe": "checking",
    "mobikwik": "checking",
    "upi lite": "checking",
    "metro card": "checking",
    "wallet": "checking",
    "cash": "cash",
}


def _infer_account_type(account_name: str) -> str:
    lower = account_name.lower()
    for hint, atype in _ACCOUNT_TYPE_HINTS.items():
        if hint in lower:
            return atype
    return "savings"


# ---------------------------------------------------------------------------
# Note-matching helpers
# ---------------------------------------------------------------------------
def _normalize_note(text: str) -> str:
    """
    Reduce a note or bank narration to comparable words.

    "UPI/SNACKS/PAYTM-1234" and "Snacks" both normalize to something the
    word-boundary matcher can line up.
    """
    if not text:
        return ""
    lowered = str(text).lower().strip()
    lowered = re.sub(r"[^a-z0-9]+", " ", lowered)
    return re.sub(r"\s+", " ", lowered).strip()


def _is_distinctive(pattern: str) -> bool:
    """
    Is this note pattern specific enough to identify a bank narration?

    Requires at least two words, one of which carries meaning. "lic policy
    premium" qualifies; "auto", "gst" and "card payment" do not.
    """
    tokens = _normalize_note(pattern).split()
    if len(tokens) < 2:
        return False
    return any(token not in NARRATION_NOISE for token in tokens)


def _note_matches(description: str, rule: Dict[str, Any]) -> bool:
    pattern = rule.get("pattern", "").lower()
    match_type = rule.get("match", "exact")
    desc = description.lower().strip()
    if match_type == "exact":
        return desc == pattern
    if match_type == "contains":
        return pattern in desc
    if match_type == "startswith":
        return desc.startswith(pattern)
    return False


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------
class ImportProfileService:
    """CRUD + apply logic for UserImportProfile."""

    def __init__(self, db: Session, user_id: str):
        self.db = db
        self.user_id = user_id
        # Auto-entry paths categorize in tight loops (a bulk AA fetch can be
        # thousands of rows), so the profile is read once per service instance.
        self._profile_cache: Optional[Dict[str, Any]] = None
        self._profile_loaded = False
        self._runtime_rules_cache: Optional[List[Dict[str, Any]]] = None

    # ------------------------------------------------------------------
    # DB access
    # ------------------------------------------------------------------
    def get_profile(self) -> Optional[Dict[str, Any]]:
        """Return the parsed config dict, or None if no profile saved yet."""
        if self._profile_loaded:
            return self._profile_cache

        row = (
            self.db.query(UserImportProfile)
            .filter(UserImportProfile.user_id == self.user_id)
            .first()
        )
        self._profile_cache = row.config if row else None
        self._profile_loaded = True
        return self._profile_cache

    def save_profile(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Upsert the profile config for this user."""
        config["version"] = 1
        row = (
            self.db.query(UserImportProfile)
            .filter(UserImportProfile.user_id == self.user_id)
            .first()
        )
        if row:
            row.config = config
        else:
            row = UserImportProfile(user_id=self.user_id, config=config)
            self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        self._profile_cache = row.config
        self._profile_loaded = True
        self._runtime_rules_cache = None
        return row.config

    # ------------------------------------------------------------------
    # Profile generation from a Money Manager file
    # ------------------------------------------------------------------
    def generate_from_file(self, file_content: bytes) -> Dict[str, Any]:
        """
        Analyse a Money Manager Excel export and return a config dict.
        Does NOT save to DB — call save_profile() to persist.
        """
        df = self._read_xlsx(file_content)
        if df is None or df.empty:
            return self._empty_config()

        df.columns = [str(c).strip() for c in df.columns]
        note_col = self._find_col(df, ["Note", "Notes"])
        cat_col = self._find_col(df, ["Category"])
        acc_col = self._find_col(df, ["Account"])
        type_col = self._find_col(df, ["Income/Expense", "Type"])

        note_rules = self._extract_note_rules(df, note_col, cat_col, type_col)
        account_mappings = self._extract_account_mappings(df, acc_col)
        category_mappings = self._extract_category_mappings(df, cat_col)
        skip_categories, skip_notes = self._extract_skip_rules(df, note_col, cat_col)

        return {
            "version": 1,
            "note_rules": note_rules,
            "account_mappings": account_mappings,
            "category_mappings": category_mappings,
            "category_vocabulary": self._extract_category_vocabulary(df, cat_col, type_col),
            "skip_categories": skip_categories,
            "skip_notes": skip_notes,
        }

    def _read_xlsx(self, file_content: bytes) -> Optional[pd.DataFrame]:
        try:
            return pd.read_excel(io.BytesIO(file_content))
        except Exception as e:
            logger.warning(f"ImportProfileService: could not read file: {e}")
            return None

    def _find_col(self, df: pd.DataFrame, candidates: List[str]) -> Optional[str]:
        for c in candidates:
            for col in df.columns:
                if col.strip().lower() == c.lower():
                    return col
        return None

    def _extract_note_rules(
        self,
        df: pd.DataFrame,
        note_col: Optional[str],
        cat_col: Optional[str],
        type_col: Optional[str],
    ) -> List[Dict[str, Any]]:
        if not note_col or not cat_col:
            return []

        # Only look at expense/income rows (skip transfers / balance adjustments)
        mask = pd.Series([True] * len(df))
        if type_col:
            mask = df[type_col].astype(str).str.lower().isin(["expense", "income"])

        cols = [note_col, cat_col] + ([type_col] if type_col else [])
        sub = df[mask][cols].dropna(subset=[note_col, cat_col])
        sub = sub[sub[note_col].astype(str).str.strip() != ""]
        sub = sub[sub[cat_col].astype(str).str.strip() != ""]

        # Count (note, category) pairs, tracking the dominant transaction type per note
        pair_counts: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
        type_counts: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
        for _, row in sub.iterrows():
            note = str(row[note_col]).strip().lower()
            cat = str(row[cat_col]).strip()
            if cat.lower() in ("nan", "none", ""):
                continue
            pair_counts[note][cat] += 1
            if type_col:
                tx_type = str(row[type_col]).strip().lower()
                if tx_type in ("expense", "income"):
                    type_counts[note][tx_type] += 1

        rules = []
        for note, cat_dist in pair_counts.items():
            total = sum(cat_dist.values())
            if total < 3:
                continue
            top_cat, top_count = max(cat_dist.items(), key=lambda x: x[1])
            confidence = top_count / total
            if confidence < 0.80:
                continue
            # Skip internal/transfer-like categories
            if top_cat.lower() in ("modified bal.", "nan", "none", ""):
                continue
            rule = {
                "pattern": note,
                "match": "exact",
                "category": top_cat,
                "frequency": total,
                "confidence": round(confidence, 2),
            }
            if type_counts.get(note):
                rule["type"] = max(type_counts[note].items(), key=lambda x: x[1])[0]
            rules.append(rule)

        # Sort by frequency desc so most-used rules win when there are overlaps
        rules.sort(key=lambda r: r["frequency"], reverse=True)
        return rules

    def _extract_account_mappings(
        self, df: pd.DataFrame, acc_col: Optional[str]
    ) -> Dict[str, Dict[str, str]]:
        if not acc_col:
            return {}
        accounts = df[acc_col].dropna().astype(str).str.strip().unique()
        mappings: Dict[str, Dict[str, str]] = {}
        for acc in accounts:
            if acc.lower() in ("nan", "none", ""):
                continue
            mappings[acc] = {
                "name": acc,
                "type": _infer_account_type(acc),
            }
        return mappings

    def _extract_category_mappings(
        self, df: pd.DataFrame, cat_col: Optional[str]
    ) -> Dict[str, str]:
        if not cat_col:
            return {}
        cats = df[cat_col].dropna().astype(str).str.strip().unique()
        return {
            c: c
            for c in cats
            if c.lower() not in ("nan", "none", "", "modified bal.")
        }

    def _extract_skip_rules(
        self,
        df: pd.DataFrame,
        note_col: Optional[str],
        cat_col: Optional[str],
    ):
        skip_categories = ["Modified Bal."]

        # Notes that are strongly associated with balance-correction categories
        skip_notes: List[str] = []
        if note_col and cat_col:
            pair_counts: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
            for _, row in df[[note_col, cat_col]].dropna().iterrows():
                note = str(row[note_col]).strip().lower()
                cat = str(row[cat_col]).strip()
                pair_counts[note][cat] += 1
            for note, cat_dist in pair_counts.items():
                total = sum(cat_dist.values())
                top_cat, top_count = max(cat_dist.items(), key=lambda x: x[1])
                if top_count / total >= 0.80 and top_cat in skip_categories:
                    skip_notes.append(note)

        return skip_categories, skip_notes

    def _empty_config(self) -> Dict[str, Any]:
        return {
            "version": 1,
            "note_rules": [],
            "account_mappings": {},
            "category_mappings": {},
            "category_vocabulary": {},
            "skip_categories": ["Modified Bal."],
            "skip_notes": [],
        }

    # ------------------------------------------------------------------
    # Applying the profile to a list of parsed TransactionCreate objects
    # ------------------------------------------------------------------
    def apply_to_transactions(
        self,
        transactions: List[TransactionCreate],
        config: Dict[str, Any],
    ) -> List[TransactionCreate]:
        """
        Filter and enrich a list of parsed TransactionCreate objects using the profile.
        Returns a (possibly shorter) list with _import_category / _import_account updated.
        """
        skip_cats = {c.lower() for c in config.get("skip_categories", [])}
        skip_notes = {n.lower() for n in config.get("skip_notes", [])}
        note_rules: List[Dict[str, Any]] = config.get("note_rules", [])
        category_mappings: Dict[str, str] = config.get("category_mappings", {})
        account_mappings: Dict[str, Dict[str, str]] = config.get("account_mappings", {})

        kept: List[TransactionCreate] = []
        for tx in transactions:
            desc = (tx.description or "").strip().lower()
            import_cat = getattr(tx, "_import_category", None) or ""
            import_acc = getattr(tx, "_import_account", None) or ""

            # 1. Skip by category
            if import_cat.lower() in skip_cats:
                continue

            # 2. Skip by note
            if desc in skip_notes:
                continue

            # 3. Apply note rules → override category
            matched_cat = self._apply_note_rules(desc, note_rules)
            if matched_cat:
                tx._import_category = matched_cat
            elif import_cat:
                # 4. Apply category mapping (rename)
                tx._import_category = category_mappings.get(import_cat, import_cat)

            # 5. Apply account mapping → set type hint on tx for entity_service
            if import_acc and import_acc in account_mappings:
                mapping = account_mappings[import_acc]
                tx._import_account = mapping.get("name", import_acc)
                tx._import_account_type = mapping.get("type", "savings")

            kept.append(tx)

        logger.info(
            f"ImportProfile applied: {len(transactions)} → {len(kept)} transactions "
            f"({len(transactions) - len(kept)} skipped)"
        )
        return kept

    def _apply_note_rules(
        self, description: str, rules: List[Dict[str, Any]]
    ) -> Optional[str]:
        for rule in rules:
            if _note_matches(description, rule):
                return rule["category"]
        return None

    # ------------------------------------------------------------------
    # Runtime matching — used for auto-created entries (SMS / AA / Gmail)
    # ------------------------------------------------------------------
    def _runtime_rules(self) -> List[Dict[str, Any]]:
        """
        Note rules trusted enough to categorize a silently-created entry,
        ordered longest-pattern-first so "cab to office" beats "cab".

        Single-word patterns are deliberately excluded. A note is the user's own
        vocabulary ("Snacks", "Fuel", "Auto"); a bank narration is the bank's
        ("BALAJI STORE", "ACH AUTO DEBIT MANDATE"). Matching one bare word across
        that gap produces far more false positives than correct hits — "auto"
        would tag every auto-debit as Transportation. Only multi-word phrases
        carry enough signal to be safe, and even those must not be pure
        narration boilerplate.
        """
        if self._runtime_rules_cache is not None:
            return self._runtime_rules_cache

        config = self.get_profile() or {}
        rules = [
            r
            for r in config.get("note_rules", [])
            if r.get("pattern")
            and r.get("frequency", 0) >= RUNTIME_MIN_FREQUENCY
            and r.get("confidence", 0) >= RUNTIME_MIN_CONFIDENCE
            and _is_distinctive(r["pattern"])
        ]
        rules.sort(key=lambda r: (len(r["pattern"]), r.get("frequency", 0)), reverse=True)
        self._runtime_rules_cache = rules
        return rules

    def match_note_rule(
        self, description: str, tx_type: Optional[TransactionType] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Find the user's own note rule matching a bank narration.

        Bank narrations are noisy ("UPI/SNACKS/PAYTM/1234"), so unlike bulk
        import this matches on word boundaries rather than whole-string equality.
        """
        if not description:
            return None

        haystack = _normalize_note(description)
        if not haystack:
            return None

        for rule in self._runtime_rules():
            rule_type = rule.get("type")
            if tx_type and rule_type and rule_type != tx_type.value:
                continue
            pattern = _normalize_note(rule["pattern"])
            if not pattern:
                continue
            if re.search(rf"(?<!\w){re.escape(pattern)}(?!\w)", haystack):
                return rule
        return None

    def resolve_category_id(
        self, description: str, tx_type: TransactionType
    ) -> Tuple[Optional[str], float]:
        """
        Map a narration to one of this user's own categories.

        Returns (category_id, confidence). Confidence is derived from how often
        the rule held in the user's history, so a mapping seen 1300 times scores
        higher than one seen 3 times.
        """
        rule = self.match_note_rule(description, tx_type)
        if not rule:
            return None, 0.0

        entity_service = ImportEntityService(self.db, self.user_id)
        category_id = entity_service.get_or_create_category(rule["category"], tx_type)
        if not category_id:
            return None, 0.0

        frequency_boost = min(rule.get("frequency", 0), 50) / 50 * 0.07
        confidence = min(0.97, 0.82 + (rule.get("confidence", 0.8) - 0.8) * 0.4 + frequency_boost)
        return category_id, round(confidence, 3)

    # ------------------------------------------------------------------
    # Category vocabulary — keep auto entries inside the user's own category set
    # ------------------------------------------------------------------
    def map_to_user_category(self, generic_name: str, tx_type: TransactionType) -> str:
        """
        Translate a built-in category name into this user's equivalent.

        The generic rules emit names like "Food & Dining" and "Healthcare". A user
        whose history uses "Food" and "Health" would otherwise end up with both,
        splitting their reporting in two. Where an equivalent exists we reuse it;
        where it genuinely doesn't, the generic name stands.

        This — not note matching — is what makes an Account Aggregator entry look
        like one the user created by hand.
        """
        if not generic_name:
            return generic_name

        config = self.get_profile() or {}

        # An explicit alias the user set always wins. Some equivalences are a
        # personal judgement no heuristic should make for them — whether
        # "Groceries" belongs under "Household", for instance.
        explicit = config.get("category_mappings", {}).get(generic_name)
        if explicit and explicit != generic_name:
            return explicit

        vocabulary = config.get("category_vocabulary", {})
        if not vocabulary:
            return generic_name

        target = _normalize_note(generic_name)
        target_tokens = {t for t in target.split() if t not in NARRATION_NOISE}

        best_name, best_score, best_count = generic_name, 0, -1
        for name, meta in vocabulary.items():
            if meta.get("type") and meta["type"] != tx_type.value:
                continue
            candidate = _normalize_note(name)
            if not candidate:
                continue

            if candidate == target:
                score = 3
            elif candidate.startswith(target) or target.startswith(candidate):
                score = 2
            elif target_tokens & {t for t in candidate.split() if t not in NARRATION_NOISE}:
                score = 1
            else:
                continue

            count = meta.get("count", 0)
            if (score, count) > (best_score, best_count):
                best_name, best_score, best_count = name, score, count

        return best_name

    def _extract_category_vocabulary(
        self,
        df: pd.DataFrame,
        cat_col: Optional[str],
        type_col: Optional[str],
    ) -> Dict[str, Dict[str, Any]]:
        """How often the user uses each of their own category names, and for what."""
        if not cat_col:
            return {}

        counts: Dict[str, int] = defaultdict(int)
        types: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
        for _, row in df[[cat_col] + ([type_col] if type_col else [])].dropna(subset=[cat_col]).iterrows():
            name = str(row[cat_col]).strip()
            if name.lower() in ("nan", "none", "", "modified bal."):
                continue
            counts[name] += 1
            if type_col:
                tx_type = str(row[type_col]).strip().lower()
                if tx_type in ("expense", "income"):
                    types[name][tx_type] += 1

        vocabulary: Dict[str, Dict[str, Any]] = {}
        for name, count in counts.items():
            entry: Dict[str, Any] = {"count": count}
            if types.get(name):
                entry["type"] = max(types[name].items(), key=lambda x: x[1])[0]
            vocabulary[name] = entry
        return vocabulary

    # ------------------------------------------------------------------
    # Bootstrapping a profile from transactions already in Prism
    # ------------------------------------------------------------------
    def generate_from_history(
        self,
        min_frequency: int = 3,
        min_confidence: float = 0.80,
    ) -> Dict[str, Any]:
        """
        Build a profile from the user's existing categorized Prism transactions.

        Same statistics as generate_from_file(), but sourced from the DB — so a
        user who never uploads a Money Manager export still gets personalised
        auto-entries once they have enough categorized history.
        Does NOT save; call save_profile() to persist.
        """
        rows = (
            self.db.query(
                Transaction.description,
                Category.name.label("category_name"),
                Category.type.label("category_type"),
            )
            .join(Category, Category.id == Transaction.category_id)
            .filter(
                Transaction.owner_id == self.user_id,
                Transaction.category_id.isnot(None),
                Transaction.description.isnot(None),
                Transaction.type != TransactionType.transfer.value,
            )
            .all()
        )

        pair_counts: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
        type_counts: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
        vocabulary: Dict[str, Dict[str, Any]] = {}
        for row in rows:
            entry = vocabulary.setdefault(row.category_name, {"count": 0})
            entry["count"] += 1
            if row.category_type in ("expense", "income"):
                entry["type"] = row.category_type

            note = _normalize_note(row.description)
            if not note:
                continue
            pair_counts[note][row.category_name] += 1
            if row.category_type in ("expense", "income"):
                type_counts[note][row.category_type] += 1

        note_rules: List[Dict[str, Any]] = []
        for note, cat_dist in pair_counts.items():
            total = sum(cat_dist.values())
            if total < min_frequency:
                continue
            top_cat, top_count = max(cat_dist.items(), key=lambda x: x[1])
            confidence = top_count / total
            if confidence < min_confidence:
                continue
            rule = {
                "pattern": note,
                "match": "exact",
                "category": top_cat,
                "frequency": total,
                "confidence": round(confidence, 2),
            }
            if type_counts.get(note):
                rule["type"] = max(type_counts[note].items(), key=lambda x: x[1])[0]
            note_rules.append(rule)

        note_rules.sort(key=lambda r: r["frequency"], reverse=True)

        config = self._empty_config()
        config["note_rules"] = note_rules
        config["category_vocabulary"] = vocabulary
        return config

    # ------------------------------------------------------------------
    # Continuous learning
    # ------------------------------------------------------------------
    def learn_note_rule(self, description: str, category_name: str, tx_type: TransactionType) -> None:
        """
        Reinforce (or create) a note rule after the user manually recategorizes.

        This is what keeps future auto-entries looking like the user's own: every
        correction they make feeds straight back into the matcher.
        """
        note = _normalize_note(description)
        if not note or not category_name:
            return

        config = self.get_profile() or self._empty_config()
        rules: List[Dict[str, Any]] = config.get("note_rules", [])

        for rule in rules:
            if _normalize_note(rule.get("pattern", "")) != note:
                continue
            if rule.get("category") == category_name:
                rule["frequency"] = rule.get("frequency", 1) + 1
                rule["confidence"] = min(1.0, round(rule.get("confidence", 0.8) + 0.02, 2))
            else:
                # The user overrode this mapping — their explicit choice wins.
                rule["category"] = category_name
                rule["frequency"] = max(RUNTIME_MIN_FREQUENCY, rule.get("frequency", 1))
                rule["confidence"] = 1.0
            rule["type"] = tx_type.value
            break
        else:
            rules.append({
                "pattern": note,
                "match": "exact",
                "category": category_name,
                "type": tx_type.value,
                # A deliberate correction is worth more than one observation, so
                # it takes effect on the next auto entry rather than after three.
                "frequency": RUNTIME_MIN_FREQUENCY,
                "confidence": 1.0,
            })

        config["note_rules"] = rules
        self.save_profile(config)
        self._runtime_rules_cache = None
