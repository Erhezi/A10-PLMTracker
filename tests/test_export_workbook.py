from app.export.workbook import render_workbook


def _cell_fill_rgb(ws, row, column):
    return ws.cell(row=row, column=column).fill.start_color.rgb


def test_render_workbook_highlights_rows_when_notes_present_without_column():
    columns = [("Item", "item")]
    rows = [
        {"item": "A123", "notes": "Needs attention"},
        {"item": "B456", "notes": None},
    ]

    workbook = render_workbook(
        sheet_name="Inventory Setup",
        rows=rows,
        columns=columns,
        highlight_notes=True,
    )

    sheet = workbook.active

    assert _cell_fill_rgb(sheet, 2, 1) == "00F8D7DA"
    assert _cell_fill_rgb(sheet, 3, 1) == "00000000"


def test_render_workbook_respects_highlight_predicate():
    columns = [("Item", "item"), ("Notes", "notes")]
    rows = [{"item": "A789", "notes": "Needs attention"}]

    workbook = render_workbook(
        sheet_name="PAR Setup",
        rows=rows,
        columns=columns,
        highlight_notes=True,
        highlight_row_predicate=lambda _: False,
    )

    sheet = workbook.active

    assert _cell_fill_rgb(sheet, 2, 1) == "00000000"
    assert _cell_fill_rgb(sheet, 2, 2) == "00000000"
