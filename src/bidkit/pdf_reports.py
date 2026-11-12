from __future__ import annotations

from xml.sax.saxutils import escape

from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

from .config import ProjectConfig
from .project_schema import require_valid_analysis


def technical_report(config: ProjectConfig) -> None:
    data = require_valid_analysis(config)
    styles = getSampleStyleSheet()
    story = [Paragraph(escape(config.project_name), styles["Title"]), Paragraph("ALKAN - revisión técnica preliminar", styles["Heading2"])]
    story.append(Paragraph(escape(data["coverage"]), styles["BodyText"]))
    story.append(Paragraph("Cantidades documentales; precios y total pendientes. Consulte los Excel y CSV para las partidas y sus fuentes. No constituye una oferta.", styles["BodyText"]))
    for key, title in (("amendments", "Adendas locales"), ("risks", "Riesgos"), ("pending", "Datos pendientes")):
        story.append(Paragraph(title, styles["Heading2"]))
        for row in data[key]:
            text = row.get("change", row.get("risk", row.get("issue", "")))
            refs = "; ".join(f"{s['document']} PDF {s['page']}" for s in row.get("sources", []))
            story.append(Paragraph(escape(f"{row['id']}: {text} {refs}"), styles["BodyText"]))
            story.append(Spacer(1, 5))
    config.output_dir.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(str(config.output_dir / "Technical_Review.pdf"), title=config.project_name, author="ALKAN", invariant=1)
    doc.build(story)
