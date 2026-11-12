"""Independent, deliberately limited evaluator of the ACTUAL QA XLSX formulas.

No eval(), formula replacement or engine imports. Unknown syntax fails closed.
Not a substitute for native Excel recalculation; COM is unavailable in this session.
All inserted values are FICTITIOUS and are written only to the separate QA copy.
"""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

from openpyxl import load_workbook
from openpyxl.formula import Tokenizer
from openpyxl.utils.cell import range_boundaries

ROOT = Path(__file__).resolve().parents[1]
QA = ROOT / "data/qa/phase-c"


class FormulaReader:
    def __init__(self, formula):
        self.tokens = [t for t in Tokenizer(formula).items if t.type != "WHITE-SPACE"]
        self.at = 0

    def parse(self, minimum=0):
        token = self.tokens[self.at]
        self.at += 1
        if token.type == "OPERATOR-PREFIX" and token.value == "-":
            node = ("negative", self.parse(5))
        elif token.type == "FUNC" and token.subtype == "OPEN":
            args = []
            while self.tokens[self.at].subtype != "CLOSE":
                args.append(self.parse())
                if self.tokens[self.at].type == "SEP":
                    self.at += 1
                else:
                    break
            assert self.tokens[self.at].type == "FUNC" and self.tokens[self.at].subtype == "CLOSE"
            self.at += 1
            node = ("function", token.value[:-1].upper(), args)
        elif token.type == "PAREN" and token.subtype == "OPEN":
            node = self.parse()
            assert self.tokens[self.at].type == "PAREN" and self.tokens[self.at].subtype == "CLOSE"
            self.at += 1
        elif token.type == "OPERAND":
            if token.subtype == "RANGE":
                node = ("reference", token.value)
            elif token.subtype == "TEXT":
                node = ("value", token.value[1:-1].replace('""', '"'))
            elif token.subtype == "NUMBER":
                node = ("value", float(token.value))
            elif token.subtype == "LOGICAL":
                node = ("value", token.value == "TRUE")
            else:
                raise ValueError((token.type, token.subtype))
        else:
            raise ValueError((token.type, token.value))
        precedence = {"=": 1, "<>": 1, ">": 1, "<": 1, ">=": 1, "<=": 1, "&": 2, "+": 3, "-": 3, "*": 4, "/": 4}
        while self.at < len(self.tokens):
            t = self.tokens[self.at]
            if t.type != "OPERATOR-INFIX" or precedence.get(t.value, -1) < minimum:
                break
            self.at += 1
            node = ("operator", t.value, node, self.parse(precedence[t.value]+1))
        return node

    def tree(self):
        tree = self.parse()
        assert self.at == len(self.tokens), "Unsupported or unconsumed formula tokens"
        return tree


def blank(value):
    return value is None or value == ""


def match(value, criterion):
    if blank(criterion):
        return blank(value)
    if isinstance(value, str) and isinstance(criterion, str):
        return value.casefold() == criterion.casefold()
    return value == criterion


class Evaluator:
    def __init__(self, book):
        self.book = book
        self.cache = {}
        self.ranges = {}

    def cell(self, sheet, address):
        key = (sheet, address)
        if key not in self.cache:
            value = self.book[sheet][address].value
            self.cache[key] = self.run(FormulaReader(value).tree(), sheet) if isinstance(value, str) and value.startswith("=") else value
        return self.cache[key]

    def run(self, node, sheet):
        kind = node[0]
        if kind == "negative": return -self.run(node[1], sheet)
        if kind == "value":
            return node[1]
        if kind == "reference":
            ref = node[1]
            if "!" in ref:
                sheet, ref = ref.rsplit("!", 1)
                sheet = sheet.strip("'").replace("''", "'")
            ref = ref.replace("$", "")
            if ":" not in ref:
                return self.cell(sheet, ref)
            a, b, c, d = range_boundaries(ref)
            key = (sheet, ref)
            if key not in self.ranges:
                self.ranges[key] = [self.cell(sheet, self.book[sheet].cell(r, col).coordinate) for r in range(b, d+1) for col in range(a, c+1)]
            return self.ranges[key]
        if kind == "operator":
            op = node[1]
            a, b = self.run(node[2], sheet), self.run(node[3], sheet)
            if op == "&": return str(a if a is not None else "") + str(b if b is not None else "")
            if op == "=": return match(a, b)
            if op == "<>": return not match(a, b)
            if a is None or a == "": a = 0
            if b is None or b == "": b = 0
            if op == ">": return a > b
            if op == "<": return a < b
            if op == ">=": return a >= b
            if op == "<=": return a <= b
            a, b = (0 if blank(a) else a), (0 if blank(b) else b)
            if op == "+": return a+b
            if op == "-": return a-b
            if op == "*": return a*b
            if op == "/": return a/b
            raise ValueError(op)
        name, args = node[1:]
        if name == "IF":
            assert len(args) == 3
            return self.run(args[1] if self.run(args[0], sheet) else args[2], sheet)
        if name == "IFERROR":
            try: return self.run(args[0], sheet)
            except (LookupError, ZeroDivisionError): return self.run(args[1], sheet)
        if name == "VLOOKUP":
            lookup = self.run(args[0], sheet)
            assert args[1][0] == "reference"
            table_sheet, ref = args[1][1].rsplit("!", 1)
            table_sheet = table_sheet.strip("'")
            first_col, start, last_col, end = range_boundaries(ref.replace("$", ""))
            col = int(self.run(args[2], sheet))
            assert self.run(args[3], sheet) is False
            for row in range(start, min(end, self.book[table_sheet].max_row)+1):
                address = self.book[table_sheet].cell(row, first_col).coordinate
                if match(self.cell(table_sheet, address), lookup):
                    return self.cell(table_sheet, self.book[table_sheet].cell(row, first_col+col-1).coordinate)
            raise LookupError("VLOOKUP: not found")
        values = [self.run(arg, sheet) for arg in args]
        if name == "OR": return any(values)
        if name == "AND": return all(values)
        if name == "ROUND":
            from decimal import Decimal, ROUND_HALF_UP
            return float(Decimal(str(values[0])).quantize(Decimal(10)**-int(values[1]), rounding=ROUND_HALF_UP))
        if name == "LEFT": return str(values[0])[:int(values[1])]
        if name == "ROWS": return len(values[0])  # Only one-column ranges occur in the workbook.
        if name == "COUNT": return sum(isinstance(v, (int, float)) and not isinstance(v, bool) for v in values[0])
        if name == "SUM": return sum(v for arg in values for v in (arg if isinstance(arg, list) else [arg]) if isinstance(v, (int, float)))
        if name == "COUNTIF": return sum(criteria_match(v, values[1]) for v in values[0])
        if name == "SUMIF":
            assert len(values[0]) == len(values[2])
            return sum(v for criteria, v in zip(values[0], values[2]) if criteria_match(criteria, values[1]) and isinstance(v, (int, float)))
        if name == "SUMIFS":
            pairs = list(zip(values[1::2], values[2::2]))
            assert all(len(v) == len(values[0]) for v, _ in pairs)
            return sum(v for index, v in enumerate(values[0]) if isinstance(v, (int, float)) and all(criteria_match(array[index], criterion) for array, criterion in pairs))
        if name == "COUNTIFS":
            pairs = list(zip(values[::2], values[1::2]))
            assert len({len(v) for v, _ in pairs}) == 1
            return sum(all(criteria_match(v[index], criterion) for v, criterion in pairs) for index in range(len(pairs[0][0])))
        raise ValueError("Unsupported function: " + name)


def criteria_match(value, criterion):
    import re
    m = re.match(r"^(<>|>=|<=|>|<|=)(.*)$", criterion) if isinstance(criterion, str) else None
    if not m: return match(value, criterion)
    op, target = m.groups()
    try: target = float(target)
    except ValueError: pass
    if op == "<>": return not match(value, target)
    if op == "=": return match(value, target)
    if blank(value): value = 0
    if op == ">": return value > target
    if op == "<": return value < target
    if op == ">=": return value >= target
    if op == "<=": return value <= target
    raise ValueError(op)


def main():
    source = ROOT / "output/orangegate-park-phase-1/Detailed_Cost_Estimate.xlsx"
    book = load_workbook(source)
    original_formulas = {(s.title, cell.coordinate): cell.value for s in book for row in s for cell in row if cell.data_type == "f"}
    # Parse every real formula before any fictitious values are inserted.
    for formula in original_formulas.values():
        FormulaReader(formula).tree()
    original = Evaluator(book)
    assert original.cell("Estimate Summary", "B2") == ""
    assert original.cell("Estimate Summary", "B5") == ""
    inputs = book["Estimate Inputs"]
    assert original.cell("Estimate Summary", "B6") == inputs.max_row-1 == 216
    scopes = {}
    for row in range(2, inputs.max_row+1):
        scopes.setdefault(inputs.cell(row, 11).value, []).append(row)
        inputs.cell(row, 5, 2)  # FICTITIOUS quantity, does not change production files.
        inputs.cell(row, 6, 3)  # FICTITIOUS unit price, never a quote.
        inputs.cell(row, 7, "FICTITIOUS_QA_ONLY_NO_COMMERCIAL_QUOTE")
    assert {k: len(v) for k, v in scopes.items()} == {"base": 144, "unallocated": 70, "alternate_5_supply_only": 1, "alternate_6_supply_only": 1}
    a = book["Assumptions"]
    a["B2"], a["B3"], a["B4"], a["B5"] = .10, 7, 1, "FICTITIOUS QA TAX TREATMENT"
    warn = book.create_sheet("QA FICTITIOUS ONLY", 0)
    warn.append(["FICTITIOUS QA ONLY - ALL QUANTITIES, PRICES, TAX AND ALLOWANCE IN THIS COPY ARE TEST VALUES."])
    warn.append(["Independent evaluation of actual formulas; native Excel COM unavailable (80070520). No native Excel recalculation claimed."])
    cases = []
    scope_row = {book["Scope Subtotals"].cell(r, 1).value: r for r in range(2, book["Scope Subtotals"].max_row+1)}
    b = scopes["base"][0]
    alt = scopes["alternate_5_supply_only"][0]
    unallocated = scopes["unallocated"][0]
    mutant = deepcopy(book)
    mutant["Estimate Inputs"][f"H{b}"] = mutant["Estimate Inputs"][f"H{b}"].value.replace("*", "+")
    assert Evaluator(mutant).cell("Estimate Summary", "B2") != 864, "Test must detect wrong arithmetic"
    mutant = deepcopy(book)
    mutant["Estimate Inputs"][f"G{b}"] = None
    mutant["Estimate Inputs"][f"H{b}"] = f"=E{b}*F{b}"
    assert Evaluator(mutant).cell("Estimate Inputs", f"H{b}") != "", "Test must detect missing quote guard"
    def scenario(name, edits, expected):
        test = deepcopy(book)
        for sheet, cell, value in edits:
            test[sheet][cell] = value
        evaluator = Evaluator(test)
        # Evaluate every formula in every scenario, not only summary assertions.
        for sheet, address in original_formulas:
            evaluator.cell(sheet, address)
        checked = []
        for sheet, address, want in expected:
            got = evaluator.cell(sheet, address)
            assert (abs(got-want) < 1e-8 if isinstance(want, (int, float)) else got == want), (name, sheet, address, got, want)
            checked.append({"sheet": sheet, "cell": address, "actual": got, "expected": want})
        cases.append({"name": name, "status": "PASS", "assertions": checked})
    scenario("All fictitious rows priced; alternates excluded from base", [], [("Estimate Summary", "B2", 864), ("Estimate Summary", "B3", 86.4), ("Estimate Summary", "B5", 957.4), ("Estimate Summary", "B6", 0), ("Scope Subtotals", f"B{scope_row['alternate_5_supply_only']}", 6), ("Scope Subtotals", f"B{scope_row['unallocated']}", 420)])
    scenario("Incomplete scope blocks total", [("Assumptions", "B4", 0)], [("Estimate Summary", "B2", ""), ("Estimate Summary", "B5", "")])
    for column, label in (("E", "quantity"), ("F", "unit price"), ("G", "quote reference")):
        scenario("Missing "+label, [("Estimate Inputs", f"{column}{b}", None)], [("Estimate Inputs", f"H{b}", ""), ("Scope Subtotals", "C2", 1), ("Estimate Summary", "B2", ""), ("Estimate Summary", "B5", ""), ("Estimate Summary", "B6", 1)])
    for column in ("E", "F"):
        scenario("Zero is valid, column "+column, [("Estimate Inputs", f"{column}{b}", 0)], [("Estimate Inputs", f"H{b}", 0), ("Estimate Summary", "B2", 858), ("Estimate Summary", "B6", 0)])
    for cell, label in (("B2", "tax rate"), ("B3", "allowance")):
        scenario("Missing "+label, [("Assumptions", cell, None)], [("Estimate Summary", "B5", "")])
    scenario("Pending tax treatment", [("Assumptions", "B5", "PENDING QA ONLY")], [("Estimate Summary", "B3", ""), ("Estimate Summary", "B5", "")])
    scenario("Alternate cost isolated", [("Estimate Inputs", f"F{alt}", 999)], [("Scope Subtotals", f"B{scope_row['alternate_5_supply_only']}", 1998), ("Estimate Summary", "B2", 864), ("Estimate Summary", "B5", 957.4)])
    scenario("Unallocated cost isolated", [("Estimate Inputs", f"F{unallocated}", 999)], [("Estimate Summary", "B2", 864), ("Estimate Summary", "B5", 957.4)])
    summary = book.create_sheet("QA Scenario Results")
    summary.append(["FICTITIOUS QA ONLY", "Result", "Assertions"])
    for case in cases:
        summary.append([case["name"], case["status"], json.dumps(case["assertions"])])
    destination = QA / "Excel_Formula_Test_FICTITIOUS.xlsx"
    book.save(destination)
    written = load_workbook(destination)
    assert all(written[sheet][cell].value == formula for (sheet, cell), formula in original_formulas.items())
    evidence = {"status": "PASS_INDEPENDENT_EVALUATOR", "native_excel_recalculated": False, "native_excel_limitation": "COM activation failed with 80070520 (logon session unavailable); independent openpyxl token parser evaluates the actual XLSX formulas. No native Excel compatibility certification.", "real_workbook": source.relative_to(ROOT).as_posix(), "qa_workbook": destination.relative_to(ROOT).as_posix(), "formulas_checked_per_scenario": len(original_formulas), "scenarios": cases, "negative_controls_detected": ["product replaced by sum", "quote guard removed"], "real_workbook_modified": False, "test_values": "FICTITIOUS: qty=2, price=3, test quote label, tax=0.10, allowance=7; never commercial quotations."}
    (QA / "excel_formula_results.json").write_text(json.dumps(evidence, indent=2)+"\n", encoding="utf-8")
    print(f"PASS: {len(cases)} scenarios x {len(original_formulas)} actual formulas; native Excel unavailable")


if __name__ == "__main__":
    main()
