"""
bill_parser.py
---------------
Converts raw OCR text into structured bill data: hospital name, patient,
bill number, dates, categorized line items, and total-mismatch detection.
Rule-based (regex + keywords) — deliberately not ML, see report for rationale.
"""

import re
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class ParsedLineItem:
    description: str
    amount: float
    category: str


@dataclass
class ParsedBill:
    hospital_name: Optional[str]
    patient_name: Optional[str]
    bill_number: Optional[str]
    admission_date: Optional[str]
    discharge_date: Optional[str]
    line_items: List[ParsedLineItem] = field(default_factory=list)
    stated_total: Optional[float] = None
    computed_total: float = 0.0
    total_mismatch: bool = False


CATEGORY_KEYWORDS = [
    (r"room\s*rent|ward|bed\s*charge", "room_rent"),
    (r"surgeon|surgery|operation|procedure|appendectomy", "procedure"),
    (r"anaesthet|anesthe", "procedure"),
    (r"nursing", "nursing"),
    (r"blood\s*test|cbc|diagnostic|scan|x-?ray|mri|ct\s*scan|ultrasound|lab\s*test", "diagnostic"),
    (r"tablet|tab\b|capsule|syrup|injection|medicine|paracetamol|mg\b", "medicine"),
    (r"consult", "consultation"),
    (r"cosmetic|non-?medical", "cosmetic"),
]
NON_COVERED_KEYWORDS = [r"cosmetic", r"non-?medical", r"non-?empanelled"]

LINE_ITEM_PATTERN = re.compile(r"^(.+?)\s{2,}(?:Rs\.?\s*)?([\d,]+\.\d{2})\s*$")
LINE_ITEM_FALLBACK = re.compile(r"^(.+?)\s+([\d,]+\.\d{2})\s*$")


def categorize(description: str) -> str:
    desc_lower = description.lower()
    for pattern, category in CATEGORY_KEYWORDS:
        if re.search(pattern, desc_lower):
            return category
    return "other"


def is_non_covered(description: str) -> bool:
    desc_lower = description.lower()
    return any(re.search(p, desc_lower) for p in NON_COVERED_KEYWORDS)


class BillParser:
    def parse(self, raw_text: str) -> ParsedBill:
        lines = [l.strip() for l in raw_text.split("\n") if l.strip()]

        hospital_name = self._extract_hospital_name(lines)
        patient_name = self._extract_field(raw_text, r"Patient\s*[:\-]?\s*([A-Za-z .]+?)(?:\s{2,}|Bill|$)")
        bill_number = self._extract_field(raw_text, r"Bill\s*No\.?\s*[:\-]?\s*([A-Za-z0-9\-\/]+)")
        admission_date = self._extract_field(raw_text, r"Admission\s*Date\s*[:\-]?\s*([\d\-A-Za-z]+)")
        discharge_date = self._extract_field(raw_text, r"Discharge\s*Date\s*[:\-]?\s*([\d\-A-Za-z]+)")

        line_items = self._extract_line_items(lines)
        stated_total = self._extract_stated_total(raw_text)
        computed_total = round(sum(item.amount for item in line_items), 2)

        total_mismatch = False
        if stated_total is not None:
            total_mismatch = abs(stated_total - computed_total) > 1.0

        return ParsedBill(
            hospital_name=hospital_name, patient_name=patient_name, bill_number=bill_number,
            admission_date=admission_date, discharge_date=discharge_date, line_items=line_items,
            stated_total=stated_total, computed_total=computed_total, total_mismatch=total_mismatch,
        )

    @staticmethod
    def _extract_field(text: str, pattern: str) -> Optional[str]:
        match = re.search(pattern, text, re.IGNORECASE)
        return match.group(1).strip() if match else None

    @staticmethod
    def _extract_hospital_name(lines: List[str]) -> Optional[str]:
        for line in lines[:5]:
            if re.search(r"hospital|clinic|medical\s*cent(er|re)|nursing\s*home", line, re.IGNORECASE):
                return line.strip()
        return lines[0] if lines else None

    def _extract_line_items(self, lines: List[str]) -> List[ParsedLineItem]:
        items = []
        skip_keywords = ["total", "amount due", "description", "hospital",
                          "patient", "bill no", "admission", "discharge", "gstin", "road"]
        in_items_section = False

        for line in lines:
            lower = line.lower()
            if "itemized" in lower and "charges" in lower:
                in_items_section = True
                continue
            if "description" in lower and "amount" in lower:
                in_items_section = True
                continue
            if "total" in lower:
                break
            if not in_items_section:
                continue
            if any(kw in lower for kw in skip_keywords):
                continue

            match = LINE_ITEM_PATTERN.match(line) or LINE_ITEM_FALLBACK.match(line)
            if match:
                desc = match.group(1).strip().rstrip(".")
                amt_str = match.group(2).replace(",", "")
                try:
                    amount = float(amt_str)
                except ValueError:
                    continue
                if amount <= 0:
                    continue
                items.append(ParsedLineItem(description=desc, amount=amount, category=categorize(desc)))
        return items

    @staticmethod
    def _extract_stated_total(text: str) -> Optional[float]:
        match = re.search(r"TOTAL\s*(?:AMOUNT\s*DUE)?\s*[:\-]?\s*(?:Rs\.?|₹)?\s*([\d,]+\.\d{2})",
                           text, re.IGNORECASE)
        return float(match.group(1).replace(",", "")) if match else None
