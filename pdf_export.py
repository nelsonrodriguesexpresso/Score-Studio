from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.colors import black, white, HexColor
from pathlib import Path
import math
import re

PAGE_W, PAGE_H = A4
MARGIN_X = 15 * mm
TOP = PAGE_H - 15 * mm
BOTTOM = 14 * mm
ACCENT = HexColor("#2F9E6D")
DARK = HexColor("#17212B")
MUTED = HexColor("#66727E")
LIGHT = HexColor("#EEF2F4")
LINE = HexColor("#4D5965")

ROOT_PC = {
    "C": 0, "C#": 1, "Db": 1, "D": 2, "D#": 3, "Eb": 3, "E": 4,
    "F": 5, "F#": 6, "Gb": 6, "G": 7, "G#": 8, "Ab": 8,
    "A": 9, "A#": 10, "Bb": 10, "B": 11,
}
BASS_OPEN = [("G", 43), ("D", 38), ("A", 33), ("E", 28), ("B", 23)]
GTR_OPEN = [("e", 64), ("B", 59), ("G", 55), ("D", 50), ("A", 45), ("E", 40)]


def safe_text(value):
    return str(value or "").replace("–", "-").replace("—", "-").replace("♭", "b").replace("♯", "#")


def root_name(chord):
    match = re.match(r"([A-G](?:#|b)?)", str(chord or "C"))
    return match.group(1) if match else "C"


def is_minor(chord):
    value = str(chord or "")
    return "m" in value and "maj" not in value.lower()


def root_midi(chord, low, high):
    pc = ROOT_PC.get(root_name(chord), 0)
    options = [m for m in range(low, high + 1) if m % 12 == pc]
    return options[0] if options else low


def adapted_pattern(chord, instrument):
    if instrument == "bass5":
        root = root_midi(chord, 23, 47)
        return [root, root + 7, root + 12, root + 7]
    if instrument == "guitar":
        root = root_midi(chord, 40, 59)
        return [root, root + 7, root + 12, root + 7]
    root = root_midi(chord, 48, 65)
    third = root + (3 if is_minor(chord) else 4)
    return [root, third, root + 7]


def choose_tab(midi, opens, max_fret=12):
    candidates = []
    for idx, (_, open_midi) in enumerate(opens):
        fret = midi - open_midi
        if 0 <= fret <= max_fret:
            candidates.append((fret, idx))
    if not candidates:
        for shift in (-12, 12, 24):
            for idx, (_, open_midi) in enumerate(opens):
                fret = (midi + shift) - open_midi
                if 0 <= fret <= max_fret:
                    candidates.append((fret, idx))
            if candidates:
                break
    return min(candidates) if candidates else (0, len(opens) - 1)


def instrument_label(instrument):
    return {
        "bass5": "Baixo - 5 cordas B-E-A-D-G",
        "guitar": "Guitarra",
        "piano": "Piano / Teclado",
    }.get(instrument, "Instrumento")


def draw_page_header(c, payload, document_name, page_no):
    c.setFillColor(DARK)
    c.rect(0, PAGE_H - 12 * mm, PAGE_W, 12 * mm, fill=1, stroke=0)
    c.setFillColor(ACCENT)
    c.rect(0, PAGE_H - 12 * mm, 4 * mm, 12 * mm, fill=1, stroke=0)
    c.setFillColor(white)
    c.setFont("Helvetica-Bold", 9)
    c.drawString(MARGIN_X, PAGE_H - 7.5 * mm, "SCORE STUDIO")
    c.setFont("Helvetica", 7.5)
    c.drawRightString(PAGE_W - MARGIN_X, PAGE_H - 7.5 * mm, safe_text(document_name))
    y = TOP - 8 * mm
    c.setFillColor(black)
    c.setFont("Helvetica-Bold", 18)
    title = safe_text(payload.get("title", "Música"))
    c.drawString(MARGIN_X, y, title[:72])
    y -= 6.5 * mm
    c.setFillColor(MUTED)
    c.setFont("Helvetica", 8.2)
    meta = (
        f"{instrument_label(payload.get('instrument'))}  |  "
        f"{safe_text(payload.get('meter', '4/4'))}  |  "
        f"{safe_text(payload.get('tempo', ''))} BPM  |  Tom: {safe_text(payload.get('key', ''))}"
    )
    c.drawString(MARGIN_X, y, meta)
    c.drawRightString(PAGE_W - MARGIN_X, y, f"Página {page_no}")
    c.setStrokeColor(LIGHT)
    c.line(MARGIN_X, y - 3.5 * mm, PAGE_W - MARGIN_X, y - 3.5 * mm)
    return y - 9 * mm


def draw_footer(c, payload):
    c.setStrokeColor(LIGHT)
    c.line(MARGIN_X, 10 * mm, PAGE_W - MARGIN_X, 10 * mm)
    c.setFillColor(MUTED)
    c.setFont("Helvetica", 6.8)
    c.drawString(MARGIN_X, 6.5 * mm, "Gerado pelo Score Studio - análise automática assistida")
    c.drawRightString(PAGE_W - MARGIN_X, 6.5 * mm, f"v{safe_text(payload.get('version', '5.0.0'))}")


def section_badge(c, x, y, width, label, repeat):
    c.setFillColor(LIGHT)
    c.roundRect(x, y - 6.5 * mm, width, 7 * mm, 2 * mm, fill=1, stroke=0)
    c.setFillColor(DARK)
    c.setFont("Helvetica-Bold", 9.5)
    text = safe_text(label).upper()
    c.drawString(x + 3 * mm, y - 4.3 * mm, text)
    if repeat and int(repeat) > 1:
        c.setFillColor(ACCENT)
        c.drawRightString(x + width - 3 * mm, y - 4.3 * mm, f"REPETIR x{int(repeat)}")


def draw_staff(c, x, y, width):
    gap = 2.9 * mm
    c.setStrokeColor(LINE)
    c.setLineWidth(0.35)
    for i in range(5):
        c.line(x, y + i * gap, x + width, y + i * gap)


def draw_note(c, x, y):
    c.setFillColor(black)
    c.saveState()
    c.translate(x, y)
    c.rotate(-17)
    c.ellipse(-2.2, -1.6, 2.2, 1.6, fill=1, stroke=0)
    c.restoreState()
    c.setStrokeColor(black)
    c.setLineWidth(0.65)
    c.line(x + 2, y, x + 2, y + 10)


def staff_y(midi, staff_base, instrument):
    ref = 43 if instrument == "bass5" else 60
    return staff_base + 5.8 * mm + (midi - ref) * 1.7


def draw_tab(c, x, y, width, chord, instrument):
    opens = BASS_OPEN if instrument == "bass5" else GTR_OPEN
    gap = 2.8 * mm
    c.setStrokeColor(LINE)
    c.setLineWidth(0.3)
    c.setFont("Helvetica", 6.3)
    c.setFillColor(MUTED)
    for idx, (name, _) in enumerate(opens):
        yy = y - idx * gap
        c.drawRightString(x - 2.3 * mm, yy - 1.8, name)
        c.line(x, yy, x + width, yy)
    c.setFillColor(black)
    for n, midi in enumerate(adapted_pattern(chord, instrument)[:4]):
        fret, string_idx = choose_tab(midi, opens)
        xx = x + (n + 0.5) * (width / 4)
        yy = y - string_idx * gap
        text = str(fret)
        c.setFont("Helvetica-Bold", 7)
        tw = c.stringWidth(text, "Helvetica-Bold", 7)
        c.setFillColor(white)
        c.rect(xx - tw / 2 - 1, yy - 3, tw + 2, 6, fill=1, stroke=0)
        c.setFillColor(black)
        c.drawCentredString(xx, yy - 2.1, text)


def measure_height(instrument):
    return 49 * mm if instrument in {"bass5", "guitar"} else 37 * mm


def draw_measure(c, x, y_top, width, height, chord, bar_no, instrument):
    c.setStrokeColor(HexColor("#B8C0C7"))
    c.setLineWidth(0.55)
    c.roundRect(x, y_top - height, width, height, 1.5 * mm, fill=0, stroke=1)
    c.setFillColor(MUTED)
    c.setFont("Helvetica", 6.2)
    c.drawString(x + 2 * mm, y_top - 3.8 * mm, str(bar_no))
    c.setFillColor(DARK)
    c.setFont("Helvetica-Bold", 11)
    c.drawCentredString(x + width / 2, y_top - 5 * mm, safe_text(chord))
    staff_base = y_top - 23 * mm
    draw_staff(c, x + 4.5 * mm, staff_base, width - 9 * mm)
    pattern = adapted_pattern(chord, instrument)
    if instrument == "piano":
        note_x = x + width * 0.40
        for midi in pattern:
            yy = staff_y(midi, staff_base, instrument)
            yy = min(staff_base + 14 * mm, max(staff_base - 2 * mm, yy))
            draw_note(c, note_x, yy)
        c.setFillColor(MUTED)
        c.setFont("Helvetica", 6.5)
        c.drawCentredString(x + width * 0.70, staff_base - 4.5 * mm, "acorde")
    else:
        for i, midi in enumerate(pattern[:4]):
            xx = x + 7 * mm + (i + 0.5) * (width - 14 * mm) / 4
            yy = staff_y(midi, staff_base, instrument)
            yy = min(staff_base + 14 * mm, max(staff_base - 2 * mm, yy))
            draw_note(c, xx, yy)
        draw_tab(c, x + 8 * mm, y_top - 34 * mm, width - 16 * mm, chord, instrument)


def create_score(payload, output):
    c = canvas.Canvas(str(output), pagesize=A4)
    instrument = payload.get("instrument", "bass5")
    page_no = 1
    y = draw_page_header(c, payload, "PAUTA DO INSTRUMENTO", page_no)
    c.setFillColor(MUTED)
    c.setFont("Helvetica", 7.2)
    c.drawString(MARGIN_X, y, "Linha instrumental adaptada aos acordes analisados. Rever antes da utilização final.")
    y -= 7 * mm
    bar_no = 1
    width = PAGE_W - 2 * MARGIN_X
    cell_width = width / 4
    h = measure_height(instrument)
    for section in payload.get("sections", []):
        chords = section.get("chords", []) or []
        if not chords:
            continue
        rows = math.ceil(len(chords) / 4)
        section_name = section.get("name", "SECÇÃO")
        repeat = section.get("repeat", 1)
        if y - (10 * mm + h) < BOTTOM:
            draw_footer(c, payload)
            c.showPage()
            page_no += 1
            y = draw_page_header(c, payload, "PAUTA DO INSTRUMENTO", page_no)
        section_badge(c, MARGIN_X, y, width, section_name, repeat)
        y -= 10 * mm
        for row_idx in range(rows):
            row = chords[row_idx * 4:(row_idx + 1) * 4]
            if y - h < BOTTOM:
                draw_footer(c, payload)
                c.showPage()
                page_no += 1
                y = draw_page_header(c, payload, "PAUTA DO INSTRUMENTO", page_no)
                section_badge(c, MARGIN_X, y, width, f"{section_name} - continuação", repeat)
                y -= 10 * mm
            for col, chord in enumerate(row):
                draw_measure(c, MARGIN_X + col * cell_width, y, cell_width - 1.2 * mm, h, chord, bar_no, instrument)
                bar_no += 1
            y -= h + 2.5 * mm
        y -= 3 * mm
    draw_footer(c, payload)
    c.save()


def create_chart(payload, output):
    c = canvas.Canvas(str(output), pagesize=A4)
    page_no = 1
    y = draw_page_header(c, payload, "PARTITURA DE ACORDES", page_no)
    width = PAGE_W - 2 * MARGIN_X
    cell_width = width / 4
    bar_no = 1
    c.setFillColor(MUTED)
    c.setFont("Helvetica", 7.2)
    c.drawString(MARGIN_X, y, "Estrutura harmónica organizada por secções e compassos.")
    y -= 8 * mm
    for section in payload.get("sections", []):
        chords = section.get("chords", []) or []
        if not chords:
            continue
        rows = math.ceil(len(chords) / 4)
        needed = 10 * mm + rows * 14 * mm
        if y - needed < BOTTOM:
            draw_footer(c, payload)
            c.showPage()
            page_no += 1
            y = draw_page_header(c, payload, "PARTITURA DE ACORDES", page_no)
        section_badge(c, MARGIN_X, y, width, section.get("name", "SECÇÃO"), section.get("repeat", 1))
        y -= 10 * mm
        for row_idx in range(rows):
            row = chords[row_idx * 4:(row_idx + 1) * 4]
            for col, chord in enumerate(row):
                x = MARGIN_X + col * cell_width
                c.setStrokeColor(HexColor("#B8C0C7"))
                c.setLineWidth(0.55)
                c.roundRect(x, y - 11 * mm, cell_width - 1.2 * mm, 11 * mm, 1.5 * mm, fill=0, stroke=1)
                c.setFillColor(MUTED)
                c.setFont("Helvetica", 6.2)
                c.drawString(x + 2 * mm, y - 3.2 * mm, str(bar_no))
                c.setFillColor(DARK)
                c.setFont("Helvetica-Bold", 14)
                c.drawCentredString(x + (cell_width - 1.2 * mm) / 2, y - 7.8 * mm, safe_text(chord))
                bar_no += 1
            y -= 13.5 * mm
        y -= 4 * mm
    draw_footer(c, payload)
    c.save()


def create_pdf(payload, output, kind):
    if kind == "chart":
        create_chart(payload, output)
    else:
        create_score(payload, output)
