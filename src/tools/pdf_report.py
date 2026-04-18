"""
PDF Report Generator — creates a downloadable GTM intelligence report.

Uses reportlab to build a professional PDF with:
- Executive summary (query, confidence, duration)
- Company profiles with ICP scores
- Enrichment signals (hiring, growth, tech stack, competitors)
- GTM strategies (hooks, email snippets, positioning)
"""

from __future__ import annotations

import io
from typing import Any

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    HRFlowable,
    KeepTogether,
)


def generate_pdf(result: dict[str, Any]) -> bytes:
    """Generate a PDF report from a PipelineResult dict. Returns raw PDF bytes."""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        topMargin=20 * mm,
        bottomMargin=20 * mm,
    )

    styles = getSampleStyleSheet()

    # Custom styles
    title_style = ParagraphStyle(
        "ReportTitle", parent=styles["Title"],
        fontSize=22, spaceAfter=4, textColor=colors.HexColor("#1a1a2e"),
    )
    subtitle_style = ParagraphStyle(
        "ReportSubtitle", parent=styles["Normal"],
        fontSize=11, textColor=colors.HexColor("#666666"), spaceAfter=16,
    )
    h2_style = ParagraphStyle(
        "H2", parent=styles["Heading2"],
        fontSize=15, spaceBefore=18, spaceAfter=8,
        textColor=colors.HexColor("#1a1a2e"),
    )
    h3_style = ParagraphStyle(
        "H3", parent=styles["Heading3"],
        fontSize=12, spaceBefore=10, spaceAfter=4,
        textColor=colors.HexColor("#333366"),
    )
    body_style = ParagraphStyle(
        "BodyText2", parent=styles["BodyText"],
        fontSize=9.5, leading=13, spaceAfter=4,
    )
    small_style = ParagraphStyle(
        "SmallText", parent=styles["BodyText"],
        fontSize=8.5, leading=11, textColor=colors.HexColor("#555555"),
    )
    label_style = ParagraphStyle(
        "Label", parent=styles["BodyText"],
        fontSize=9, leading=11, textColor=colors.HexColor("#888888"),
    )
    hook_style = ParagraphStyle(
        "HookText", parent=styles["BodyText"],
        fontSize=9.5, leading=13, leftIndent=10,
        borderColor=colors.HexColor("#4a90d9"), borderWidth=1,
        borderPadding=6, backColor=colors.HexColor("#f0f5ff"),
    )
    email_style = ParagraphStyle(
        "EmailText", parent=styles["BodyText"],
        fontSize=9, leading=12, leftIndent=10,
        fontName="Courier", backColor=colors.HexColor("#f8f8f0"),
        borderPadding=6,
    )

    story = []

    # --- Title ---
    story.append(Paragraph("Outmate.ai — GTM Intelligence Report", title_style))
    story.append(Paragraph(
        f"Query: <i>{_esc(result.get('query', 'N/A'))}</i>",
        subtitle_style,
    ))
    story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#ddd")))
    story.append(Spacer(1, 6))

    # --- Executive Summary ---
    plan = result.get("plan", {})
    confidence = result.get("confidence", 0)
    duration_ms = result.get("total_duration_ms", 0)
    retries = result.get("retries", 0)
    companies = result.get("results", [])
    strategies_list = result.get("gtm_strategy", {}).get("strategies", [])
    icp_scores = result.get("icp_scores", [])

    summary_data = [
        ["Confidence", f"{confidence:.0%}"],
        ["Companies Found", str(len(companies))],
        ["Strategies Generated", str(len(strategies_list))],
        ["Duration", f"{duration_ms / 1000:.1f}s"],
        ["Retries", str(retries)],
    ]
    summary_table = Table(summary_data, colWidths=[120, 120])
    summary_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f5f5f5")),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#ddd")),
    ]))
    story.append(summary_table)
    story.append(Spacer(1, 6))

    # Strategy summary
    strategy_text = plan.get("strategy", "")
    if strategy_text:
        story.append(Paragraph(f"<b>Strategy:</b> {_esc(strategy_text)}", body_style))
    story.append(Spacer(1, 4))

    # --- Build lookup maps ---
    score_map = {s["company_id"]: s for s in icp_scores}
    strategy_map = {s["company_id"]: s for s in strategies_list}

    # Sort companies by ICP score
    companies_sorted = sorted(
        companies,
        key=lambda c: score_map.get(c["company"]["company_id"], {}).get("composite_score", 0),
        reverse=True,
    )

    # --- Company Profiles ---
    story.append(Paragraph("Company Profiles", h2_style))
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#ddd")))

    for idx, ec in enumerate(companies_sorted):
        company = ec.get("company", {})
        cid = company.get("company_id", "")
        score = score_map.get(cid, {})
        strategy = strategy_map.get(cid, {})

        company_block = []

        # Company header
        rank = idx + 1
        name = company.get("name", "Unknown")
        industry = company.get("industry", "N/A")
        geo = company.get("geography", "N/A")
        emp = company.get("employee_count", "N/A")
        funding = company.get("funding_stage", "N/A")
        domain = company.get("domain", "")
        desc = company.get("description", "")
        composite = score.get("composite_score", 0)

        company_block.append(Paragraph(
            f"#{rank} — {_esc(name)}",
            h3_style,
        ))

        # Company info table
        info_data = [
            ["Domain", domain or "N/A", "Industry", industry or "N/A"],
            ["Geography", (geo or "N/A").upper(), "Employees", str(emp)],
            ["Funding", funding or "N/A", "ICP Score", f"{composite:.2f}"],
        ]
        info_table = Table(info_data, colWidths=[70, 100, 70, 100])
        info_table.setStyle(TableStyle([
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("TEXTCOLOR", (0, 0), (0, -1), colors.HexColor("#888")),
            ("TEXTCOLOR", (2, 0), (2, -1), colors.HexColor("#888")),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
        ]))
        company_block.append(info_table)

        if desc:
            company_block.append(Paragraph(f"<i>{_esc(desc)}</i>", small_style))

        # ICP Score breakdown
        breakdown = score.get("breakdown", {})
        if breakdown:
            fit = score.get("fit_score", 0)
            intent = score.get("intent_score", 0)
            growth = score.get("growth_score", 0)
            company_block.append(Paragraph(
                f"<b>ICP Breakdown:</b> Fit {fit:.2f} | Intent {intent:.2f} | Growth {growth:.2f} | "
                f"<b>Composite {composite:.2f}</b>",
                small_style,
            ))

        # Signals
        hiring = ec.get("hiring")
        if hiring and hiring.get("open_roles"):
            notable = ", ".join(hiring.get("notable_roles", [])[:3])
            company_block.append(Paragraph(
                f"<b>Hiring:</b> {hiring['open_roles']} open roles "
                f"({hiring.get('engineering_roles', 0)} eng, {hiring.get('sales_roles', 0)} sales)"
                f"{' — ' + notable if notable else ''}",
                body_style,
            ))

        growth_sig = ec.get("growth")
        if growth_sig:
            parts = []
            if growth_sig.get("revenue_estimate"):
                parts.append(f"Revenue: {growth_sig['revenue_estimate']}")
            if growth_sig.get("employee_growth_6m") is not None:
                parts.append(f"6m growth: {growth_sig['employee_growth_6m']:.0%}")
            if growth_sig.get("web_traffic_trend"):
                parts.append(f"Traffic: {growth_sig['web_traffic_trend']}")
            if parts:
                company_block.append(Paragraph(f"<b>Growth:</b> {' | '.join(parts)}", body_style))

        tech = ec.get("tech_stack")
        if tech and tech.get("detected_technologies"):
            techs = ", ".join(tech["detected_technologies"][:6])
            company_block.append(Paragraph(f"<b>Tech Stack:</b> {_esc(techs)}", body_style))

        competitors = ec.get("competitors")
        if competitors and competitors.get("likely_competitors"):
            comps = ", ".join(competitors["likely_competitors"][:4])
            company_block.append(Paragraph(f"<b>Competitors:</b> {_esc(comps)}", body_style))
            if competitors.get("churn_indicators"):
                churns = ", ".join(competitors["churn_indicators"][:3])
                company_block.append(Paragraph(f"<b>Churn Signals:</b> {_esc(churns)}", small_style))

        # GTM Strategy
        if strategy:
            hooks = strategy.get("hooks", [])
            emails = strategy.get("email_snippets", [])
            positioning = strategy.get("competitive_positioning", "")
            channel = strategy.get("recommended_channel", "")

            company_block.append(Spacer(1, 4))
            company_block.append(Paragraph("<b>GTM Strategy</b>", body_style))

            if channel:
                company_block.append(Paragraph(f"Recommended channel: <b>{_esc(channel)}</b>", label_style))

            for hook in hooks[:2]:
                company_block.append(Paragraph(
                    f"<b>[{_esc(hook.get('persona', ''))}]</b> {_esc(hook.get('hook', ''))}",
                    hook_style,
                ))
                if hook.get("angle"):
                    company_block.append(Paragraph(
                        f"<i>Angle: {_esc(hook['angle'])}</i>", small_style,
                    ))

            for email in emails[:2]:
                company_block.append(Spacer(1, 4))
                company_block.append(Paragraph(
                    f"<b>Email — [{_esc(email.get('persona', ''))}]</b> "
                    f"Subject: {_esc(email.get('subject', ''))}",
                    body_style,
                ))
                body_text = email.get("body", "").replace("\n", "<br/>")
                company_block.append(Paragraph(_esc(body_text), email_style))

            if positioning:
                company_block.append(Paragraph(
                    f"<b>Positioning:</b> {_esc(positioning)}", small_style,
                ))

        company_block.append(Spacer(1, 4))
        company_block.append(HRFlowable(width="100%", thickness=0.3, color=colors.HexColor("#eee")))

        story.append(KeepTogether(company_block))

    # --- Agent Trace ---
    trace = result.get("reasoning_trace", [])
    if trace:
        story.append(Paragraph("Agent Execution Trace", h2_style))
        trace_data = [["Agent", "Status", "Duration", "Attempt"]]
        for step in trace:
            dur = step.get("duration_ms")
            trace_data.append([
                step.get("agent", ""),
                step.get("status", ""),
                f"{dur:.0f}ms" if dur is not None else "N/A",
                str(step.get("attempt", 1)),
            ])
        trace_table = Table(trace_data, colWidths=[100, 80, 80, 60])
        trace_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#333366")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#ddd")),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8f8f8")]),
        ]))
        story.append(trace_table)

    # --- Footer ---
    story.append(Spacer(1, 20))
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#ccc")))
    story.append(Paragraph(
        "Generated by Outmate.ai — Multi-Agent GTM Intelligence System",
        ParagraphStyle("Footer", parent=styles["Normal"], fontSize=8,
                       textColor=colors.HexColor("#aaa"), alignment=1),
    ))

    doc.build(story)
    return buf.getvalue()


def _esc(text: str) -> str:
    """Escape XML special chars for reportlab Paragraph."""
    if not text:
        return ""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )
