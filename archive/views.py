from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from accounts.decorators import admin_required
from hcndash.exports import export_csv, export_xlsx

from .forms import DatasetUploadForm, ManualDatasetForm, NewPeriodForm, build_row_form
from .models import Dataset, Periode, Row
from .services import parse_uploaded_file

IS_AJAX_HEADER = "XMLHttpRequest"


def _is_ajax(request):
    return request.headers.get("X-Requested-With") == IS_AJAX_HEADER


@login_required
def period_list(request):
    periodes = Periode.objects.annotate(dataset_count=Count("datasets"))
    if request.method == "POST":
        form = NewPeriodForm(request.POST)
        if form.is_valid():
            periode = Periode.objects.create(
                numero=form.cleaned_data["numero"],
                annee=form.cleaned_data["annee"],
                created_by=request.user,
            )
            messages.success(request, f"Période {periode.libelle} créée.")
            return redirect("archive:period_detail", mois_id=periode.id)
    else:
        form = NewPeriodForm()

    soumis_count = periodes.filter(statut=Periode.STATUT_SOUMIS).count()
    return render(
        request,
        "archive/period_list.html",
        {
            "periodes": periodes,
            "form": form,
            "total_count": periodes.count(),
            "soumis_count": soumis_count,
            "brouillon_count": periodes.count() - soumis_count,
        },
    )


@login_required
def period_detail(request, mois_id):
    periode = get_object_or_404(Periode, pk=mois_id)
    datasets = periode.datasets.annotate(row_count=Count("rows"))
    return render(
        request,
        "archive/period_detail.html",
        {
            "periode": periode,
            "datasets": datasets,
            "can_manage": request.user.profile.is_admin,
        },
    )


@login_required
def period_submit(request, mois_id):
    periode = get_object_or_404(Periode, pk=mois_id)
    if request.method == "POST" and not periode.est_verrouillee:
        periode.statut = Periode.STATUT_SOUMIS
        periode.soumis_par = request.user
        periode.soumis_at = timezone.now()
        periode.save()
        messages.success(request, f"Période {periode.libelle} soumise et verrouillée.")
    return redirect("archive:period_detail", mois_id=periode.id)


@admin_required
def period_reopen(request, mois_id):
    periode = get_object_or_404(Periode, pk=mois_id)
    if request.method == "POST":
        periode.statut = Periode.STATUT_BROUILLON
        periode.save()
        messages.warning(request, f"Période {periode.libelle} rouverte pour modification.")
    return redirect("archive:period_detail", mois_id=periode.id)


@admin_required
def period_delete(request, mois_id):
    periode = get_object_or_404(Periode, pk=mois_id)
    if request.method == "POST":
        libelle = periode.libelle
        periode.delete()
        messages.success(request, f"Période {libelle} et ses jeux de données supprimés.")
        return redirect("archive:period_list")
    return render(request, "archive/period_confirm_delete.html", {"periode": periode})


@login_required
def period_export(request, mois_id, fmt):
    periode = get_object_or_404(Periode, pk=mois_id)
    sheets = [
        (dataset.name, dataset.columns, [[row.data.get(c, "") for c in dataset.columns] for row in dataset.rows.all()])
        for dataset in periode.datasets.all()
    ]
    filename = f"archive_{periode.annee}_{periode.numero:02d}"
    if fmt == "csv":
        if len(sheets) == 1:
            _, columns, rows = sheets[0]
            return export_csv(filename, columns, rows)
        # Flatten multiple datasets into one CSV with a leading "Dataset" column.
        all_columns = sorted({c for _, columns, _ in sheets for c in columns})
        flat_rows = []
        for name, columns, rows in sheets:
            for row in rows:
                by_col = dict(zip(columns, row))
                flat_rows.append([name] + [by_col.get(c, "") for c in all_columns])
        return export_csv(filename, ["Dataset"] + all_columns, flat_rows)
    return export_xlsx(filename, sheets)


@login_required
def upload_dataset(request, mois_id):
    periode = get_object_or_404(Periode, pk=mois_id)
    if periode.est_verrouillee:
        messages.error(request, "Cette période est soumise et verrouillée. Rouvrez-la pour la modifier.")
        return redirect("archive:period_detail", mois_id=periode.id)

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
                    name=name, columns=columns, periode=periode, created_by=request.user
                )
                Row.objects.bulk_create([Row(dataset=dataset, data=record) for record in records])
                if records:
                    messages.success(
                        request, f'« {dataset.name} » importé avec {len(records)} ligne(s).'
                    )
                else:
                    messages.warning(
                        request,
                        f'« {dataset.name} » importé, mais aucune ligne de données trouvée — '
                        "seules les colonnes ont été créées.",
                    )
                return redirect("archive:dataset_detail", pk=dataset.pk)
    else:
        form = DatasetUploadForm()
    return render(request, "archive/dataset_upload.html", {"form": form, "periode": periode})


@login_required
def add_dataset_manual(request, mois_id):
    periode = get_object_or_404(Periode, pk=mois_id)
    if periode.est_verrouillee:
        messages.error(request, "Cette période est soumise et verrouillée. Rouvrez-la pour la modifier.")
        return redirect("archive:period_detail", mois_id=periode.id)

    if request.method == "POST":
        form = ManualDatasetForm(request.POST)
        if form.is_valid():
            dataset = Dataset.objects.create(
                name=form.cleaned_data["name"],
                columns=form.cleaned_data["columns"],
                periode=periode,
                created_by=request.user,
            )
            messages.success(request, f'Jeu de données « {dataset.name} » créé. Ajoutez des lignes ci-dessous.')
            return redirect("archive:dataset_detail", pk=dataset.pk)
    else:
        form = ManualDatasetForm()
    return render(request, "archive/dataset_manual_form.html", {"form": form, "periode": periode})


@login_required
def dataset_detail(request, pk):
    dataset = get_object_or_404(Dataset, pk=pk)
    rows = dataset.rows.all()
    return render(
        request,
        "archive/dataset_detail.html",
        {
            "dataset": dataset,
            "rows": rows,
            "can_manage": request.user.profile.is_admin,
        },
    )


@admin_required
def dataset_delete(request, pk):
    dataset = get_object_or_404(Dataset, pk=pk)
    if request.method == "POST":
        periode_id = dataset.periode_id
        name = dataset.name
        dataset.delete()
        messages.success(request, f'Jeu de données "{name}" supprimé.')
        if periode_id:
            return redirect("archive:period_detail", mois_id=periode_id)
        return redirect("archive:period_list")
    return render(request, "archive/dataset_confirm_delete.html", {"dataset": dataset})


@login_required
def dataset_export(request, pk, fmt):
    dataset = get_object_or_404(Dataset, pk=pk)
    rows = [[row.data.get(c, "") for c in dataset.columns] for row in dataset.rows.all()]
    if fmt == "csv":
        return export_csv(dataset.name, dataset.columns, rows)
    return export_xlsx(dataset.name, [(dataset.name, dataset.columns, rows)])


@login_required
def add_row(request, pk):
    dataset = get_object_or_404(Dataset, pk=pk)
    if dataset.periode and dataset.periode.est_verrouillee:
        if _is_ajax(request):
            return JsonResponse({"status": "locked"}, status=409)
        messages.error(request, "Cette période est soumise et verrouillée. Rouvrez-la pour la modifier.")
        return redirect("archive:dataset_detail", pk=dataset.pk)

    if request.method == "POST":
        form = build_row_form(dataset.columns, data=request.POST)
        if form.is_valid():
            row = Row.objects.create(dataset=dataset, data=form.cleaned_data)
            if _is_ajax(request):
                return JsonResponse({"status": "ok", "row_id": row.id})
            messages.success(request, "Ligne ajoutée.")
            return redirect("archive:dataset_detail", pk=dataset.pk)
        if _is_ajax(request):
            return JsonResponse({"status": "invalid", "errors": form.errors}, status=400)
    else:
        form = build_row_form(dataset.columns)
    return render(
        request,
        "archive/row_form.html",
        {"form": form, "dataset": dataset, "title": "Ajouter une ligne"},
    )


@login_required
def edit_row(request, pk, row_id):
    dataset = get_object_or_404(Dataset, pk=pk)
    row = get_object_or_404(Row, pk=row_id, dataset=dataset)
    if dataset.periode and dataset.periode.est_verrouillee:
        if _is_ajax(request):
            return JsonResponse({"status": "locked"}, status=409)
        messages.error(request, "Cette période est soumise et verrouillée. Rouvrez-la pour la modifier.")
        return redirect("archive:dataset_detail", pk=dataset.pk)

    if request.method == "POST":
        form = build_row_form(dataset.columns, data=request.POST)
        if form.is_valid():
            row.data = form.cleaned_data
            row.save(update_fields=["data", "updated_at"])
            if _is_ajax(request):
                return JsonResponse({"status": "ok"})
            messages.success(request, "Ligne modifiée.")
            return redirect("archive:dataset_detail", pk=dataset.pk)
        if _is_ajax(request):
            return JsonResponse({"status": "invalid", "errors": form.errors}, status=400)
    else:
        form = build_row_form(dataset.columns, initial=row.data)
    return render(
        request,
        "archive/row_form.html",
        {"form": form, "dataset": dataset, "row": row, "title": "Modifier la ligne"},
    )


@login_required
def delete_row(request, pk, row_id):
    dataset = get_object_or_404(Dataset, pk=pk)
    row = get_object_or_404(Row, pk=row_id, dataset=dataset)
    if dataset.periode and dataset.periode.est_verrouillee:
        messages.error(request, "Cette période est soumise et verrouillée. Rouvrez-la pour la modifier.")
        return redirect("archive:dataset_detail", pk=dataset.pk)
    if request.method == "POST":
        row.delete()
        messages.success(request, "Ligne supprimée.")
        return redirect("archive:dataset_detail", pk=dataset.pk)
    return render(
        request, "archive/row_confirm_delete.html", {"dataset": dataset, "row": row}
    )
