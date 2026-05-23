from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from html import escape
from pathlib import Path
import pandas as pd
from fastapi import HTTPException
from sqlalchemy.orm import Session, joinedload

from database import SessionLocal
from models import EmailReportPreference, ReportJob, Transaction
from services.email_templates import render_monthly_summary_email

REPORTS_BASE_DIR = Path(__file__).resolve().parents[1] / "generated_reports"
REPORTS_BASE_DIR.mkdir(parents=True, exist_ok=True)

EXPENSE_KEYWORDS_FOR_TAX = {
    "tax",
    "rent",
    "utilities",
    "healthcare",
    "insurance",
    "education",
    "travel",
}


def run_report_job(report_id: str, session_factory=None) -> dict[str, str]:
    session_factory = session_factory or SessionLocal
    db = session_factory()
    try:
        report = ReportService(db).generate_report_job(report_id)
        return {
            "report_id": report.id,
            "file_path": report.file_path,
            "download_url": f"/api/v1/reports/{report.id}/download",
        }
    finally:
        db.close()


class ReportService:
    def __init__(self, db: Session):
        self.db = db

    def create_report_job(
        self,
        user_id: str,
        report_type: str,
        period_start: date,
        period_end: date,
        output_format: str,
    ) -> ReportJob:
        if period_start > period_end:
            raise HTTPException(status_code=400, detail="period_start must be before or equal to period_end")

        job = ReportJob(
            user_id=user_id,
            report_type=report_type,
            period_start=period_start,
            period_end=period_end,
            format=output_format,
            status="pending",
        )
        self.db.add(job)
        self.db.commit()
        self.db.refresh(job)
        return job

    def generate_report_job(self, report_id: str) -> ReportJob:
        job = self.db.query(ReportJob).filter(ReportJob.id == report_id).first()
        if job is None:
            raise HTTPException(status_code=404, detail="Report not found")

        try:
            job.status = "running"
            job.file_path = None
            job.error_message = None
            job.completed_at = None
            self.db.commit()

            path = self._generate_report_file(job.user_id, job.report_type, job.period_start, job.period_end, job.format)
            job.file_path = str(path)
            job.status = "completed"
            job.completed_at = datetime.now(timezone.utc)
            self.db.commit()
            self.db.refresh(job)
            return job
        except Exception as exc:
            job.status = "failed"
            job.error_message = str(exc)
            job.completed_at = datetime.now(timezone.utc)
            self.db.commit()
            self.db.refresh(job)
            raise

    def list_report_jobs(self, user_id: str) -> list[ReportJob]:
        return (
            self.db.query(ReportJob)
            .filter(ReportJob.user_id == user_id)
            .order_by(ReportJob.created_at.desc())
            .all()
        )

    def get_report_job(self, user_id: str, report_id: str) -> ReportJob:
        report = (
            self.db.query(ReportJob)
            .filter(ReportJob.user_id == user_id, ReportJob.id == report_id)
            .first()
        )
        if not report:
            raise HTTPException(status_code=404, detail="Report not found")
        return report

    def resolve_report_path(self, report: ReportJob) -> Path:
        if not report.file_path:
            raise HTTPException(status_code=404, detail="Report file not found")

        path = Path(report.file_path).resolve()
        base = REPORTS_BASE_DIR.resolve()
        try:
            path.relative_to(base)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid report path") from exc

        if not path.exists():
            raise HTTPException(status_code=404, detail="Report file not found")
        return path

    def build_download_name(self, report: ReportJob) -> str:
        extension = "html" if report.format == "pdf" else report.format
        return f"{report.report_type}_{report.period_start.isoformat()}_{report.period_end.isoformat()}.{extension}"

    @staticmethod
    def get_media_type(output_format: str, path: Path) -> str:
        if output_format == "csv":
            return "text/csv"
        if output_format == "xlsx":
            return "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        if path.suffix == ".html":
            return "text/html"
        return "application/octet-stream"

    def generate_monthly_summary(self, user_id: str, year: int, month: int) -> dict:
        period_start = date(year, month, 1)
        if month == 12:
            period_end = date(year, 12, 31)
        else:
            period_end = date(year, month + 1, 1) - timedelta(days=1)

        transactions = self._get_transactions(user_id, period_start, period_end)
        totals = self._calculate_totals(transactions)
        top_categories = self._top_categories(transactions)

        return {
            "period_start": period_start,
            "period_end": period_end,
            "period_label": period_start.strftime("%B %Y"),
            "total_income": totals["income"],
            "total_expenses": totals["expense"],
            "savings": totals["income"] - totals["expense"],
            "transaction_count": len(transactions),
            "top_categories": top_categories,
            "transactions": self._transaction_rows(transactions),
        }

    def generate_category_breakdown(self, user_id: str, start_date: date, end_date: date) -> dict:
        transactions = self._get_transactions(user_id, start_date, end_date)
        categories: dict[str, dict] = {}
        total_spend = 0.0

        for transaction in transactions:
            if transaction.type != "expense":
                continue

            category_name = transaction.category.name if transaction.category else "Uncategorized"
            entry = categories.setdefault(
                category_name,
                {"category": category_name, "amount": 0.0, "transaction_count": 0},
            )
            entry["amount"] += float(transaction.amount)
            entry["transaction_count"] += 1
            total_spend += float(transaction.amount)

        ordered_categories = sorted(categories.values(), key=lambda item: item["amount"], reverse=True)
        for item in ordered_categories:
            item["percentage"] = round((item["amount"] / total_spend) * 100, 2) if total_spend else 0.0

        return {
            "period_start": start_date,
            "period_end": end_date,
            "period_label": self._format_period_label(start_date, end_date),
            "total_spend": total_spend,
            "transaction_count": len([tx for tx in transactions if tx.type == "expense"]),
            "categories": ordered_categories,
            "transactions": self._transaction_rows(transactions),
        }

    def generate_cash_flow_report(self, user_id: str, start_date: date, end_date: date) -> dict:
        transactions = self._get_transactions(user_id, start_date, end_date)
        daily: dict[str, dict] = {}
        weekly: dict[str, dict] = {}
        totals = self._calculate_totals(transactions)

        for transaction in transactions:
            tx_date = transaction.date.date()
            daily_key = tx_date.isoformat()
            daily_entry = daily.setdefault(
                daily_key,
                {"date": daily_key, "income": 0.0, "expense": 0.0, "net": 0.0},
            )

            iso_year, iso_week, _ = tx_date.isocalendar()
            weekly_key = f"{iso_year}-W{iso_week:02d}"
            weekly_entry = weekly.setdefault(
                weekly_key,
                {"week": weekly_key, "income": 0.0, "expense": 0.0, "net": 0.0},
            )

            amount = float(transaction.amount)
            if transaction.type == "income":
                daily_entry["income"] += amount
                daily_entry["net"] += amount
                weekly_entry["income"] += amount
                weekly_entry["net"] += amount
            elif transaction.type == "expense":
                daily_entry["expense"] += amount
                daily_entry["net"] -= amount
                weekly_entry["expense"] += amount
                weekly_entry["net"] -= amount

        return {
            "period_start": start_date,
            "period_end": end_date,
            "period_label": self._format_period_label(start_date, end_date),
            "total_income": totals["income"],
            "total_expenses": totals["expense"],
            "net_cash_flow": totals["income"] - totals["expense"],
            "transaction_count": len(transactions),
            "daily": [daily[key] for key in sorted(daily)],
            "weekly": [weekly[key] for key in sorted(weekly)],
            "transactions": self._transaction_rows(transactions),
        }

    def generate_tax_report(self, user_id: str, start_date: date, end_date: date) -> dict:
        transactions = self._get_transactions(user_id, start_date, end_date)
        totals = self._calculate_totals(transactions)
        category_breakdown = self.generate_category_breakdown(user_id, start_date, end_date)
        monthly_buckets: dict[str, dict] = defaultdict(lambda: {"income": 0.0, "expense": 0.0, "net": 0.0})
        deductible_candidates = []

        for transaction in transactions:
            month_key = transaction.date.strftime("%Y-%m")
            amount = float(transaction.amount)
            if transaction.type == "income":
                monthly_buckets[month_key]["income"] += amount
                monthly_buckets[month_key]["net"] += amount
            elif transaction.type == "expense":
                monthly_buckets[month_key]["expense"] += amount
                monthly_buckets[month_key]["net"] -= amount
                category_name = (transaction.category.name if transaction.category else "Uncategorized").lower()
                if any(keyword in category_name for keyword in EXPENSE_KEYWORDS_FOR_TAX):
                    deductible_candidates.append({
                        "date": transaction.date.date().isoformat(),
                        "description": transaction.description,
                        "category": transaction.category.name if transaction.category else "Uncategorized",
                        "amount": amount,
                    })

        monthly_breakdown = [
            {"month": month, **values}
            for month, values in sorted(monthly_buckets.items())
        ]

        return {
            "period_start": start_date,
            "period_end": end_date,
            "period_label": self._format_period_label(start_date, end_date),
            "total_income": totals["income"],
            "total_expenses": totals["expense"],
            "net_income": totals["income"] - totals["expense"],
            "transaction_count": len(transactions),
            "expense_categories": category_breakdown["categories"],
            "monthly_breakdown": monthly_breakdown,
            "deductible_candidates": deductible_candidates,
            "transactions": self._transaction_rows(transactions),
        }

    def export_transactions_csv(
        self,
        user_id: str,
        start_date: date,
        end_date: date,
        filters: dict | None = None,
    ) -> Path:
        transactions = self._get_transactions(user_id, start_date, end_date, filters)
        dataframe = pd.DataFrame(self._transaction_rows(transactions))
        path = self._build_output_path(user_id, "transactions_export", "csv")
        dataframe.to_csv(path, index=False)
        return path

    def export_transactions_xlsx(
        self,
        user_id: str,
        start_date: date,
        end_date: date,
        filters: dict | None = None,
    ) -> Path:
        transactions = self._get_transactions(user_id, start_date, end_date, filters)
        dataframe = pd.DataFrame(self._transaction_rows(transactions))
        path = self._build_output_path(user_id, "transactions_export", "xlsx")
        with pd.ExcelWriter(path, engine="openpyxl") as writer:
            dataframe.to_excel(writer, sheet_name="transactions", index=False)
        return path

    def schedule_email_report(self, user_id: str, report_type: str, frequency: str) -> EmailReportPreference:
        preference = (
            self.db.query(EmailReportPreference)
            .filter(
                EmailReportPreference.user_id == user_id,
                EmailReportPreference.report_type == report_type,
            )
            .first()
        )
        if preference is None:
            preference = EmailReportPreference(
                user_id=user_id,
                report_type=report_type,
                frequency=frequency,
            )
            self.db.add(preference)
        else:
            preference.frequency = frequency
            preference.is_enabled = True
            preference.updated_at = datetime.now(timezone.utc)

        self.db.commit()
        self.db.refresh(preference)
        return preference

    def _generate_report_file(
        self,
        user_id: str,
        report_type: str,
        period_start: date,
        period_end: date,
        output_format: str,
    ) -> Path:
        data = self._get_report_payload(user_id, report_type, period_start, period_end)

        if output_format == "pdf":
            path = self._build_output_path(user_id, report_type, "html")
            path.write_text(self._render_html_report(report_type, data), encoding="utf-8")
            return path

        if output_format == "csv":
            path = self._build_output_path(user_id, report_type, "csv")
            self._report_dataframe(report_type, data).to_csv(path, index=False)
            return path

        if output_format == "xlsx":
            path = self._build_output_path(user_id, report_type, "xlsx")
            self._write_excel_report(path, report_type, data)
            return path

        raise HTTPException(status_code=400, detail="Unsupported report format")

    def _get_report_payload(self, user_id: str, report_type: str, period_start: date, period_end: date) -> dict:
        if report_type == "monthly_summary":
            return self.generate_monthly_summary(user_id, period_start.year, period_start.month)
        if report_type == "category_breakdown":
            return self.generate_category_breakdown(user_id, period_start, period_end)
        if report_type == "cash_flow":
            return self.generate_cash_flow_report(user_id, period_start, period_end)
        if report_type == "tax_report":
            return self.generate_tax_report(user_id, period_start, period_end)
        raise HTTPException(status_code=400, detail="Unsupported report type")

    def _write_excel_report(self, path: Path, report_type: str, data: dict) -> None:
        with pd.ExcelWriter(path, engine="openpyxl") as writer:
            self._report_dataframe(report_type, data).to_excel(writer, sheet_name="summary", index=False)

            if report_type == "monthly_summary":
                pd.DataFrame(data["top_categories"]).to_excel(writer, sheet_name="top_categories", index=False)
            elif report_type == "category_breakdown":
                pd.DataFrame(data["categories"]).to_excel(writer, sheet_name="categories", index=False)
            elif report_type == "cash_flow":
                pd.DataFrame(data["daily"]).to_excel(writer, sheet_name="daily_cash_flow", index=False)
                pd.DataFrame(data["weekly"]).to_excel(writer, sheet_name="weekly_cash_flow", index=False)
            elif report_type == "tax_report":
                pd.DataFrame(data["expense_categories"]).to_excel(writer, sheet_name="expense_categories", index=False)
                pd.DataFrame(data["monthly_breakdown"]).to_excel(writer, sheet_name="monthly_breakdown", index=False)
                pd.DataFrame(data["deductible_candidates"]).to_excel(writer, sheet_name="deductible_candidates", index=False)

            pd.DataFrame(data["transactions"]).to_excel(writer, sheet_name="transactions", index=False)

    def _report_dataframe(self, report_type: str, data: dict) -> pd.DataFrame:
        if report_type == "monthly_summary":
            rows = [
                {"section": "summary", "label": "period", "value": data["period_label"]},
                {"section": "summary", "label": "total_income", "value": data["total_income"]},
                {"section": "summary", "label": "total_expenses", "value": data["total_expenses"]},
                {"section": "summary", "label": "savings", "value": data["savings"]},
                {"section": "summary", "label": "transaction_count", "value": data["transaction_count"]},
            ]
            rows.extend(
                {
                    "section": "top_category",
                    "label": item["category"],
                    "value": item["amount"],
                    "transaction_count": item["transaction_count"],
                }
                for item in data["top_categories"]
            )
            return pd.DataFrame(rows)

        if report_type == "category_breakdown":
            return pd.DataFrame(data["categories"])

        if report_type == "cash_flow":
            return pd.DataFrame(data["daily"])

        if report_type == "tax_report":
            rows = [
                {"section": "summary", "label": "period", "value": data["period_label"]},
                {"section": "summary", "label": "total_income", "value": data["total_income"]},
                {"section": "summary", "label": "total_expenses", "value": data["total_expenses"]},
                {"section": "summary", "label": "net_income", "value": data["net_income"]},
                {"section": "summary", "label": "transaction_count", "value": data["transaction_count"]},
            ]
            rows.extend(
                {"section": "expense_category", "label": item["category"], "value": item["amount"], "percentage": item["percentage"]}
                for item in data["expense_categories"]
            )
            rows.extend(
                {"section": "month", "label": item["month"], "income": item["income"], "expense": item["expense"], "net": item["net"]}
                for item in data["monthly_breakdown"]
            )
            return pd.DataFrame(rows)

        raise HTTPException(status_code=400, detail="Unsupported report type")

    def _get_transactions(self, user_id: str, start_date: date, end_date: date, filters: dict | None = None) -> list[Transaction]:
        start_dt = datetime.combine(start_date, time.min)
        end_dt = datetime.combine(end_date, time.max)
        query = (
            self.db.query(Transaction)
            .options(joinedload(Transaction.category), joinedload(Transaction.account))
            .filter(Transaction.owner_id == user_id)
            .filter(Transaction.date >= start_dt)
            .filter(Transaction.date <= end_dt)
        )

        filters = filters or {}
        if filters.get("account_id"):
            query = query.filter(Transaction.account_id == filters["account_id"])
        if filters.get("category_ids"):
            query = query.filter(Transaction.category_id.in_(filters["category_ids"]))
        if filters.get("search"):
            search_term = f"%{filters['search']}%"
            query = query.filter(
                (Transaction.description.ilike(search_term)) | (Transaction.notes.ilike(search_term))
            )

        return query.order_by(Transaction.date.asc()).all()

    @staticmethod
    def _calculate_totals(transactions: list[Transaction]) -> dict[str, float]:
        income = sum(float(tx.amount) for tx in transactions if tx.type == "income")
        expense = sum(float(tx.amount) for tx in transactions if tx.type == "expense")
        return {"income": income, "expense": expense}

    @staticmethod
    def _top_categories(transactions: list[Transaction]) -> list[dict]:
        buckets: dict[str, dict] = {}
        for transaction in transactions:
            if transaction.type != "expense":
                continue
            category_name = transaction.category.name if transaction.category else "Uncategorized"
            entry = buckets.setdefault(
                category_name,
                {"category": category_name, "amount": 0.0, "transaction_count": 0},
            )
            entry["amount"] += float(transaction.amount)
            entry["transaction_count"] += 1
        return sorted(buckets.values(), key=lambda item: item["amount"], reverse=True)[:5]

    @staticmethod
    def _transaction_rows(transactions: list[Transaction]) -> list[dict]:
        return [
            {
                "date": transaction.date.isoformat(),
                "type": transaction.type,
                "description": transaction.description,
                "merchant": transaction.merchant,
                "category": transaction.category.name if transaction.category else "Uncategorized",
                "account": transaction.account.name if transaction.account else None,
                "amount": float(transaction.amount),
                "currency": transaction.account.currency if transaction.account else "INR",
                "notes": transaction.notes,
            }
            for transaction in transactions
        ]

    def _render_html_report(self, report_type: str, data: dict) -> str:
        if report_type == "monthly_summary":
            return render_monthly_summary_email(data)

        if report_type == "category_breakdown":
            categories_table = self._build_html_table(
                data["categories"],
                [("category", "Category"), ("amount", "Amount"), ("percentage", "Share %"), ("transaction_count", "Transactions")],
            )
            body = (
                self._metric_cards([
                    ("Total spend", data["total_spend"]),
                    ("Expense transactions", data["transaction_count"]),
                ])
                + f"<h2>Category breakdown</h2>{categories_table}"
            )
            return self._wrap_html("Category Breakdown", data["period_label"], body)

        if report_type == "cash_flow":
            daily_table = self._build_html_table(
                data["daily"],
                [("date", "Date"), ("income", "Income"), ("expense", "Expense"), ("net", "Net")],
            )
            weekly_table = self._build_html_table(
                data["weekly"],
                [("week", "Week"), ("income", "Income"), ("expense", "Expense"), ("net", "Net")],
            )
            body = (
                self._metric_cards([
                    ("Income", data["total_income"]),
                    ("Expenses", data["total_expenses"]),
                    ("Net cash flow", data["net_cash_flow"]),
                ])
                + f"<h2>Daily cash flow</h2>{daily_table}<h2>Weekly cash flow</h2>{weekly_table}"
            )
            return self._wrap_html("Cash Flow Report", data["period_label"], body)

        if report_type == "tax_report":
            monthly_table = self._build_html_table(
                data["monthly_breakdown"],
                [("month", "Month"), ("income", "Income"), ("expense", "Expense"), ("net", "Net")],
            )
            category_table = self._build_html_table(
                data["expense_categories"],
                [("category", "Category"), ("amount", "Amount"), ("percentage", "Share %")],
            )
            deductible_table = self._build_html_table(
                data["deductible_candidates"],
                [("date", "Date"), ("description", "Description"), ("category", "Category"), ("amount", "Amount")],
            )
            body = (
                self._metric_cards([
                    ("Income", data["total_income"]),
                    ("Expenses", data["total_expenses"]),
                    ("Net income", data["net_income"]),
                ])
                + f"<h2>Monthly view</h2>{monthly_table}<h2>Expense categories</h2>{category_table}<h2>Potentially relevant expenses</h2>{deductible_table}"
            )
            return self._wrap_html("Tax Report", data["period_label"], body)

        raise HTTPException(status_code=400, detail="Unsupported report type")

    @staticmethod
    def _wrap_html(title: str, subtitle: str, body: str) -> str:
        return f"""
        <!DOCTYPE html>
        <html lang=\"en\">
          <head>
            <meta charset=\"utf-8\" />
            <meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\" />
            <title>{escape(title)}</title>
            <style>
              body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; margin: 0; background: #f8fafc; color: #0f172a; }}
              .page {{ max-width: 960px; margin: 0 auto; padding: 32px 20px 48px; }}
              .hero {{ background: linear-gradient(135deg, #0f172a, #2563eb); color: white; padding: 28px; border-radius: 22px; margin-bottom: 24px; }}
              .cards {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 16px; margin-bottom: 24px; }}
              .card {{ background: white; border-radius: 18px; padding: 18px; box-shadow: 0 10px 30px rgba(15, 23, 42, 0.06); border: 1px solid #e2e8f0; }}
              h2 {{ margin: 24px 0 12px; font-size: 20px; }}
              table {{ width: 100%; border-collapse: collapse; background: white; border-radius: 18px; overflow: hidden; box-shadow: 0 10px 30px rgba(15, 23, 42, 0.06); }}
              th, td {{ padding: 14px 16px; border-bottom: 1px solid #e2e8f0; font-size: 14px; text-align: left; }}
              th {{ background: #eff6ff; color: #1e3a8a; font-size: 12px; text-transform: uppercase; letter-spacing: 0.06em; }}
              td.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
            </style>
          </head>
          <body>
            <div class=\"page\">
              <div class=\"hero\">
                <p style=\"margin:0 0 8px;opacity:.8;text-transform:uppercase;letter-spacing:.08em;font-size:13px;\">Prism report</p>
                <h1 style=\"margin:0;font-size:32px;\">{escape(title)}</h1>
                <p style=\"margin:10px 0 0;font-size:15px;opacity:.9;\">{escape(subtitle)}</p>
              </div>
              {body}
            </div>
          </body>
        </html>
        """

    def _metric_cards(self, items: list[tuple[str, float | int]]) -> str:
        cards = "".join(
            f"<div class='card'><div style='font-size:12px;text-transform:uppercase;color:#64748b;font-weight:700;letter-spacing:.05em'>{escape(label)}</div><div style='font-size:28px;font-weight:800;margin-top:10px'>{self._format_value(value)}</div></div>"
            for label, value in items
        )
        return f"<div class='cards'>{cards}</div>"

    def _build_html_table(self, rows: list[dict], columns: list[tuple[str, str]]) -> str:
        if not rows:
            return "<div class='card'>No data available for this period.</div>"

        headers = "".join(f"<th>{escape(label)}</th>" for _, label in columns)
        body_rows = []
        for row in rows:
            cells = []
            for key, _ in columns:
                value = row.get(key, "")
                class_name = " class='num'" if isinstance(value, (int, float)) else ""
                cells.append(f"<td{class_name}>{escape(self._format_value(value))}</td>")
            body_rows.append(f"<tr>{''.join(cells)}</tr>")
        return f"<table><thead><tr>{headers}</tr></thead><tbody>{''.join(body_rows)}</tbody></table>"

    def _build_output_path(self, user_id: str, report_type: str, extension: str) -> Path:
        user_dir = REPORTS_BASE_DIR / user_id
        user_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
        return user_dir / f"{report_type}_{timestamp}.{extension}"

    @staticmethod
    def _format_period_label(start_date: date, end_date: date) -> str:
        return f"{start_date.strftime('%b %d, %Y')} – {end_date.strftime('%b %d, %Y')}"

    @staticmethod
    def _format_value(value) -> str:
        if isinstance(value, float):
            return f"₹{value:,.2f}"
        if isinstance(value, int):
            return f"{value:,}"
        return str(value)
