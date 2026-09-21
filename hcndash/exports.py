import csv

from django.http import HttpResponse
from openpyxl import Workbook


def export_csv(filename, columns, rows):
    """rows: iterable of iterables, same order as columns."""
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = f'attachment; filename="{filename}.csv"'
    writer = csv.writer(response)
    writer.writerow(columns)
    writer.writerows(rows)
    return response


def export_xlsx(filename, sheets):
    """sheets: [(sheet_name, columns, rows), ...] — one worksheet per entry."""
    wb = Workbook()
    wb.remove(wb.active)
    for name, columns, rows in sheets:
        ws = wb.create_sheet(title=str(name)[:31])
        ws.append(list(columns))
        for row in rows:
            ws.append(list(row))

    response = HttpResponse(
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    response["Content-Disposition"] = f'attachment; filename="{filename}.xlsx"'
    wb.save(response)
    return response
