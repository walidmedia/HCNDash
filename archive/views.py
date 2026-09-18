from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count
from django.shortcuts import get_object_or_404, redirect, render

from .forms import DatasetUploadForm, ManualDatasetForm, build_row_form
from .models import Dataset, Row
from .services import parse_uploaded_file


@login_required
def dashboard(request):
    datasets = Dataset.objects.annotate(row_count=Count("rows"))
    return render(request, "archive/dashboard.html", {"datasets": datasets})


@login_required
def upload_dataset(request):
    if request.method == "POST":
        form = DatasetUploadForm(request.POST, request.FILES)
        if form.is_valid():
            uploaded_file = form.cleaned_data["file"]
            try:
                columns, records = parse_uploaded_file(uploaded_file)
            except ValueError as exc:
                form.add_error("file", str(exc))
            else:
                name = form.cleaned_data["name"].strip() or uploaded_file.name.rsplit(".", 1)[0]
                dataset = Dataset.objects.create(
                    name=name, columns=columns, created_by=request.user
                )
                Row.objects.bulk_create([Row(dataset=dataset, data=record) for record in records])
                if records:
                    messages.success(
                        request, f'Uploaded "{dataset.name}" with {len(records)} rows.'
                    )
                else:
                    messages.warning(
                        request,
                        f'Uploaded "{dataset.name}", but no data rows were found — '
                        "only columns were created.",
                    )
                return redirect("archive:dataset_detail", pk=dataset.pk)
    else:
        form = DatasetUploadForm()
    return render(request, "archive/dataset_upload.html", {"form": form})


@login_required
def add_dataset_manual(request):
    if request.method == "POST":
        form = ManualDatasetForm(request.POST)
        if form.is_valid():
            dataset = Dataset.objects.create(
                name=form.cleaned_data["name"],
                columns=form.cleaned_data["columns"],
                created_by=request.user,
            )
            messages.success(request, f'Created dataset "{dataset.name}". Add rows below.')
            return redirect("archive:dataset_detail", pk=dataset.pk)
    else:
        form = ManualDatasetForm()
    return render(request, "archive/dataset_manual_form.html", {"form": form})


@login_required
def dataset_detail(request, pk):
    dataset = get_object_or_404(Dataset, pk=pk)
    rows = dataset.rows.all()
    return render(request, "archive/dataset_detail.html", {"dataset": dataset, "rows": rows})


@login_required
def add_row(request, pk):
    dataset = get_object_or_404(Dataset, pk=pk)
    if request.method == "POST":
        form = build_row_form(dataset.columns, data=request.POST)
        if form.is_valid():
            Row.objects.create(dataset=dataset, data=form.cleaned_data)
            messages.success(request, "Row added.")
            return redirect("archive:dataset_detail", pk=dataset.pk)
    else:
        form = build_row_form(dataset.columns)
    return render(
        request,
        "archive/row_form.html",
        {"form": form, "dataset": dataset, "title": "Add row"},
    )


@login_required
def edit_row(request, pk, row_id):
    dataset = get_object_or_404(Dataset, pk=pk)
    row = get_object_or_404(Row, pk=row_id, dataset=dataset)
    if request.method == "POST":
        form = build_row_form(dataset.columns, data=request.POST)
        if form.is_valid():
            row.data = form.cleaned_data
            row.save(update_fields=["data", "updated_at"])
            messages.success(request, "Row updated.")
            return redirect("archive:dataset_detail", pk=dataset.pk)
    else:
        form = build_row_form(dataset.columns, initial=row.data)
    return render(
        request,
        "archive/row_form.html",
        {"form": form, "dataset": dataset, "title": "Edit row"},
    )


@login_required
def delete_row(request, pk, row_id):
    dataset = get_object_or_404(Dataset, pk=pk)
    row = get_object_or_404(Row, pk=row_id, dataset=dataset)
    if request.method == "POST":
        row.delete()
        messages.success(request, "Row deleted.")
        return redirect("archive:dataset_detail", pk=dataset.pk)
    return render(
        request, "archive/row_confirm_delete.html", {"dataset": dataset, "row": row}
    )
