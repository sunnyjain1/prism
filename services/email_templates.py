from html import escape


def _format_currency(amount: float) -> str:
    return f"₹{amount:,.2f}"


def render_monthly_summary_email(data: dict) -> str:
    top_categories = "".join(
        f"""
        <tr>
            <td style=\"padding:12px 0;border-bottom:1px solid #e5e7eb;color:#111827;\">{escape(str(item.get('category', 'Uncategorized')))}</td>
            <td style=\"padding:12px 0;border-bottom:1px solid #e5e7eb;text-align:right;color:#111827;font-weight:600;\">{_format_currency(float(item.get('amount', 0)))}</td>
        </tr>
        """
        for item in data.get("top_categories", [])[:5]
    ) or "<tr><td colspan='2' style='padding:12px 0;color:#6b7280;'>No spending categories for this period.</td></tr>"

    return f"""
    <!DOCTYPE html>
    <html lang=\"en\">
      <head>
        <meta charset=\"utf-8\" />
        <meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\" />
        <title>Prism Monthly Summary</title>
      </head>
      <body style=\"margin:0;padding:0;background:#f3f4f6;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;color:#111827;\">
        <div style=\"max-width:640px;margin:0 auto;padding:24px 16px;\">
          <div style=\"background:#ffffff;border-radius:20px;overflow:hidden;box-shadow:0 10px 30px rgba(15,23,42,0.08);\">
            <div style=\"padding:28px 24px;background:linear-gradient(135deg,#1d4ed8,#7c3aed);color:#ffffff;\">
              <p style=\"margin:0 0 8px;font-size:13px;letter-spacing:0.08em;text-transform:uppercase;opacity:0.85;\">Prism Report</p>
              <h1 style=\"margin:0;font-size:28px;line-height:1.2;\">Monthly Summary</h1>
              <p style=\"margin:10px 0 0;font-size:15px;opacity:0.9;\">{escape(str(data.get('period_label', 'Selected period')))}</p>
            </div>

            <div style=\"padding:24px;\">
              <div style=\"display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px;margin-bottom:24px;\">
                <div style=\"padding:16px;border:1px solid #d1fae5;border-radius:16px;background:#ecfdf5;\">
                  <div style=\"font-size:12px;color:#047857;text-transform:uppercase;font-weight:700;letter-spacing:0.05em;\">Income</div>
                  <div style=\"margin-top:8px;font-size:24px;font-weight:700;color:#065f46;\">{_format_currency(float(data.get('total_income', 0)))}</div>
                </div>
                <div style=\"padding:16px;border:1px solid #fee2e2;border-radius:16px;background:#fef2f2;\">
                  <div style=\"font-size:12px;color:#b91c1c;text-transform:uppercase;font-weight:700;letter-spacing:0.05em;\">Expenses</div>
                  <div style=\"margin-top:8px;font-size:24px;font-weight:700;color:#991b1b;\">{_format_currency(float(data.get('total_expenses', 0)))}</div>
                </div>
                <div style=\"padding:16px;border:1px solid #dbeafe;border-radius:16px;background:#eff6ff;\">
                  <div style=\"font-size:12px;color:#1d4ed8;text-transform:uppercase;font-weight:700;letter-spacing:0.05em;\">Savings</div>
                  <div style=\"margin-top:8px;font-size:24px;font-weight:700;color:#1e3a8a;\">{_format_currency(float(data.get('savings', 0)))}</div>
                </div>
              </div>

              <div style=\"margin-bottom:24px;padding:18px;border:1px solid #e5e7eb;border-radius:16px;background:#f9fafb;\">
                <div style=\"font-size:13px;color:#6b7280;margin-bottom:8px;\">Transaction count</div>
                <div style=\"font-size:28px;font-weight:700;\">{int(data.get('transaction_count', 0))}</div>
              </div>

              <h2 style=\"margin:0 0 12px;font-size:18px;\">Top 5 categories</h2>
              <table role=\"presentation\" width=\"100%\" cellspacing=\"0\" cellpadding=\"0\" style=\"border-collapse:collapse;font-size:14px;\">
                <thead>
                  <tr>
                    <th align=\"left\" style=\"padding-bottom:10px;color:#6b7280;font-size:12px;text-transform:uppercase;letter-spacing:0.05em;\">Category</th>
                    <th align=\"right\" style=\"padding-bottom:10px;color:#6b7280;font-size:12px;text-transform:uppercase;letter-spacing:0.05em;\">Amount</th>
                  </tr>
                </thead>
                <tbody>
                  {top_categories}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      </body>
    </html>
    """
