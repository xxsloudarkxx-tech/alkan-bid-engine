import fs from "node:fs/promises";
import { FileBlob, SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const root = process.cwd();
const outputDir = `${root}/output`;
const takeoff = JSON.parse(await fs.readFile(`${root}/data/takeoff/takeoff.json`, "utf8"));
const estimate = JSON.parse(await fs.readFile(`${root}/data/estimate/estimate_inputs.json`, "utf8"));
const audit = JSON.parse(await fs.readFile(`${root}/data/audit/bid_audit.json`, "utf8"));
await fs.mkdir(outputDir, { recursive: true });

const blue = "#1F4E78";
const pale = "#F3F7FB";
const amber = "#FFF2CC";
const red = "#FCE4D6";
function title(sheet, text, range) {
  sheet.getRange(range).merge();
  sheet.getRange(range.split(":")[0]).values = [[text]];
  sheet.getRange(range).format = { fill: blue, font: { bold: true, color: "#FFFFFF", size: 14 }, horizontalAlignment: "left", verticalAlignment: "center" };
  sheet.getRange(range).format.rowHeight = 26;
}
function header(range) {
  range.format = { fill: blue, font: { bold: true, color: "#FFFFFF" }, horizontalAlignment: "center", verticalAlignment: "center", wrapText: true, borders: { preset: "all", style: "thin", color: "#D9D9D9" } };
}
function body(range) {
  range.format = { verticalAlignment: "center", wrapText: true, borders: { preset: "all", style: "thin", color: "#D9D9D9" } };
}
function setWidth(sheet, columns) { columns.forEach(([col, width]) => sheet.getRange(`${col}:${col}`).format.columnWidth = width); }

const takeoffBook = Workbook.create();
const to = takeoffBook.worksheets.add("Takeoff");
to.showGridLines = false;
title(to, "Material Takeoff - Controlled Working Draft", "A1:G1");
to.getRange("A3:G3").values = [["Building", "Item", "Unit", "Quantity", "Quantity status", "Basis", "Source"]]; header(to.getRange("A3:G3"));
to.getRangeByIndexes(3, 0, takeoff.records.length, 7).values = takeoff.records.map(r => [r.building, r.item, r.unit, r.quantity ?? "", r.quantity_status, r.basis, `${r.source.document} | ${r.source.page} | ${r.source.confidence}`]);
body(to.getRange(`A4:G${3 + takeoff.records.length}`));
to.getRange(`D4:D${3 + takeoff.records.length}`).format.numberFormat = "#,##0.00";
to.getRange(`D4:D${3 + takeoff.records.length}`).conditionalFormats.add("containsBlanks", { format: { fill: amber, font: { color: "#7F6000", bold: true } } });
setWidth(to, [["A", 28], ["B", 34], ["C", 14], ["D", 14], ["E", 25], ["F", 54], ["G", 40]]);
to.freezePanes.freezeRows(3);
const req = takeoffBook.worksheets.add("Bid Checklist");
req.showGridLines = false;
title(req, "Compliance and Bid Submission Checklist", "A1:F1");
req.getRange("A3:F3").values = [["Phase", "ID", "Requirement", "Status", "Evidence owner", "Source"]]; header(req.getRange("A3:F3"));
req.getRangeByIndexes(3, 0, audit.requirements.length, 6).values = audit.requirements.map(r => [r.phase, r.id, r.requirement, r.status, "", `${r.source.document} | p. ${r.source.page}`]);
body(req.getRange(`A4:F${3 + audit.requirements.length}`));
req.getRange(`D4:D${3 + audit.requirements.length}`).conditionalFormats.add("containsText", { text: "BLOCKING", format: { fill: red, font: { bold: true, color: "#9C0006" } } });
setWidth(req, [["A", 22], ["B", 12], ["C", 62], ["D", 15], ["E", 28], ["F", 34]]);
req.freezePanes.freezeRows(3);
await takeoffBook.recalculate();
let preview = await takeoffBook.render({ sheetName: "Takeoff", range: "A1:G18", scale: 1, format: "png" });
await fs.writeFile(`${outputDir}/qa_takeoff_preview.png`, new Uint8Array(await preview.arrayBuffer()));
let xlsx = await SpreadsheetFile.exportXlsx(takeoffBook); await xlsx.save(`${outputDir}/Material_Takeoff.xlsx`);

const estimateBook = Workbook.create();
const summary = estimateBook.worksheets.add("Estimate Summary");
const inputs = estimateBook.worksheets.add("Estimate Inputs");
const assumptions = estimateBook.worksheets.add("Assumptions");
const risks = estimateBook.worksheets.add("Risks and Clarifications");
[summary, inputs, assumptions, risks].forEach(s => s.showGridLines = false);
title(assumptions, "Controlled Assumptions", "A1:D1");
assumptions.getRange("A3:D3").values = [["Parameter", "Value", "Status", "Source"]]; header(assumptions.getRange("A3:D3"));
assumptions.getRange("A4:D5").values = [["Washington State Sales Tax", estimate.tax_rate, estimate.tax_rate_status, "072026-1044_specs.pdf | 00 41 00 p. 1"], ["Unforeseen Conditions Allowance", estimate.allowance, estimate.allowance_status, "072026-1044_specs.pdf | 00 41 00 p. 1"]];
body(assumptions.getRange("A4:D5")); assumptions.getRange("B4").format.numberFormat = "0.0%"; assumptions.getRange("B5").format.numberFormat = '"$"#,##0';
setWidth(assumptions, [["A", 34], ["B", 18], ["C", 24], ["D", 48]]);
title(inputs, "Detailed Cost Estimate - Inputs", "A1:J1");
inputs.getRange("A3:J3").values = [["Bid item", "Cost class", "UOM", "Qty", "Unit price", "Source / quote ref", "Extended cost", "Status", "Estimator approval", "Notes"]]; header(inputs.getRange("A3:J3"));
inputs.getRangeByIndexes(3, 0, estimate.rows.length, 10).values = estimate.rows.map(r => [r.bid_item, r.cost_class, r.uom, 1, r.fixed_amount ?? "", "", "", r.status, "PENDING", ""]);
for (let row = 4; row < 4 + estimate.rows.length; row++) inputs.getRange(`G${row}`).formulas = [[`=IF(OR(D${row}="",E${row}=""),"",D${row}*E${row})`]];
body(inputs.getRange(`A4:J${3 + estimate.rows.length}`));
inputs.getRange(`E4:F${3 + estimate.rows.length}`).format.fill = amber;
inputs.getRange(`I4:I${3 + estimate.rows.length}`).format.fill = amber;
inputs.getRange(`E4:E${3 + estimate.rows.length}`).format.numberFormat = '"$"#,##0.00'; inputs.getRange(`G4:G${3 + estimate.rows.length}`).format.numberFormat = '"$"#,##0.00';
setWidth(inputs, [["A", 33], ["B", 25], ["C", 10], ["D", 10], ["E", 15], ["F", 27], ["G", 17], ["H", 21], ["I", 21], ["J", 36]]); inputs.freezePanes.freezeRows(3);
title(summary, "Detailed Cost Estimate - Review Summary", "A1:D1");
summary.getRange("A3:D3").values = [["Metric", "Value", "Status", "Control"]]; header(summary.getRange("A3:D3"));
summary.getRange("A4:D8").values = [["Base Bid Subtotal", "", "BLOCKED until all supported prices and approvals are supplied", "Includes allowance once all other costs are priced"], ["WSST", "", "BLOCKED", "10.5% of Base Bid Subtotal"], ["Bid Total With WSST", "", "BLOCKED", "Official Bid Form controls"], ["Unpriced rows", "", "PENDING", "Must be zero before estimator approval"], ["Allowance", "", "VERIFIED", "Fixed at $25,000 in current Bid Form"]];
summary.getRange("B4").formulas = [[`=IF(COUNTBLANK('Estimate Inputs'!E4:E16)>0,"",SUM('Estimate Inputs'!G4:G17))`]];
summary.getRange("B5").formulas = [[`=IF(B4="","",B4*Assumptions!B4)`]]; summary.getRange("B6").formulas = [[`=IF(OR(B4="",B5=""),"",B4+B5)`]]; summary.getRange("B7").formulas = [[`=COUNTBLANK('Estimate Inputs'!E4:E16)`]]; summary.getRange("B8").formulas = [["=Assumptions!B5"]];
body(summary.getRange("A4:D8")); summary.getRange("B4:B6").format.numberFormat = '"$"#,##0.00'; summary.getRange("B8").format.numberFormat = '"$"#,##0.00';
summary.getRange("B4:B6").format.fill = red; summary.getRange("B7").format.fill = amber; setWidth(summary, [["A", 30], ["B", 22], ["C", 52], ["D", 42]]);
title(risks, "Risk and Clarification Register", "A1:E1");
risks.getRange("A3:E3").values = [["ID", "Status", "Risk / clarification", "Required action", "Source"]]; header(risks.getRange("A3:E3"));
risks.getRangeByIndexes(3, 0, audit.risks.length, 5).values = audit.risks.map(r => [r.id, r.status, r.risk, r.action, `${r.source.document} | p. ${r.source.page}`]);
body(risks.getRange(`A4:E${3 + audit.risks.length}`)); setWidth(risks, [["A", 10], ["B", 15], ["C", 52], ["D", 52], ["E", 38]]); risks.freezePanes.freezeRows(3);
await estimateBook.recalculate();
preview = await estimateBook.render({ sheetName: "Estimate Summary", range: "A1:D10", scale: 1, format: "png" });
await fs.writeFile(`${outputDir}/qa_estimate_preview.png`, new Uint8Array(await preview.arrayBuffer()));
xlsx = await SpreadsheetFile.exportXlsx(estimateBook); await xlsx.save(`${outputDir}/Detailed_Cost_Estimate.xlsx`);
console.log(JSON.stringify({ takeoff: `${outputDir}/Material_Takeoff.xlsx`, estimate: `${outputDir}/Detailed_Cost_Estimate.xlsx` }));
