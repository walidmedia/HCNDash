from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.db import transaction
from django.db.models import Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from .audit import record_change, snapshot_before
from .forms import (
    NewPeriodForm,
    build_emploi_form,
    build_investissement_form,
    build_objectifs_form,
    build_section_form,
)
from .models import (
    Categorie,
    ChangeLog,
    DontEffectif,
    Effectif,
    LigneMesure,
    Mesure,
    Mois,
    MontantInvestissement,
    Objectif,
    PeriodeRapport,
    Rapport,
    Structure,
)

MESURE_FIELD_MAP = {
    "prev": "valeur_previsionnel",
    "real": "valeur_realisation",
    "realn1": "valeur_realisation_n1",
    "cumulprev": "valeur_previsionnel_cumul",
    "cumulreal": "valeur_realisation_cumul",
    "cumulrealn1": "valeur_realisation_cumul_n1",
}

MESURE_SUM_FIELDS = list(MESURE_FIELD_MAP.values())


def _rapport_completion(rapport, mois):
    total = LigneMesure.objects.filter(master_entite__rapport=rapport).count()
    filled = (
        Mesure.objects.filter(
            ligne_mesure__master_entite__rapport=rapport, mois=mois, valeur_realisation__isnull=False
        )
        .values("ligne_mesure_id")
        .distinct()
        .count()
    )
    return filled, total


def _emploi_completion(mois):
    total = Categorie.objects.count()
    filled = (
        Effectif.objects.filter(mois=mois, valeur__isnull=False).values("categorie_id").distinct().count()
    )
    return filled, total


def _investissement_completion(mois):
    total = Structure.objects.count()
    filled = (
        MontantInvestissement.objects.filter(mois=mois, valeur_realisation__isnull=False)
        .values("structure_id")
        .distinct()
        .count()
    )
    return filled, total


@login_required
def period_list(request):
    periodes = (
        PeriodeRapport.objects.select_related("mois", "soumis_par").all()
    )
    if request.method == "POST":
        form = NewPeriodForm(request.POST)
        if form.is_valid():
            mois = Mois.objects.create(
                numero=form.cleaned_data["numero"], annee=form.cleaned_data["annee"]
            )
            PeriodeRapport.objects.create(mois=mois)
            messages.success(request, f"Période {mois} créée.")
            return redirect("spe_report:period_detail", mois_id=mois.id)
    else:
        form = NewPeriodForm()

    soumis_count = periodes.filter(statut=PeriodeRapport.STATUT_SOUMIS).count()
    return render(
        request,
        "spe_report/period_list.html",
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
    mois = get_object_or_404(Mois, pk=mois_id)
    periode, _ = PeriodeRapport.objects.get_or_create(mois=mois)

    rapport_rows = []
    for rapport in Rapport.objects.order_by("ordre"):
        filled, total = _rapport_completion(rapport, mois)
        rapport_rows.append({"rapport": rapport, "filled": filled, "total": total})

    emploi_filled, emploi_total = _emploi_completion(mois)
    invest_filled, invest_total = _investissement_completion(mois)

    return render(
        request,
        "spe_report/period_detail.html",
        {
            "mois": mois,
            "periode": periode,
            "rapport_rows": rapport_rows,
            "emploi_filled": emploi_filled,
            "emploi_total": emploi_total,
            "invest_filled": invest_filled,
            "invest_total": invest_total,
            "can_reopen": request.user.has_perm("spe_report.reopen_periode"),
        },
    )


@login_required
def period_submit(request, mois_id):
    mois = get_object_or_404(Mois, pk=mois_id)
    periode, _ = PeriodeRapport.objects.get_or_create(mois=mois)
    if request.method == "POST" and not periode.est_verrouillee:
        periode.statut = PeriodeRapport.STATUT_SOUMIS
        periode.soumis_par = request.user
        periode.soumis_at = timezone.now()
        periode.save()
        messages.success(request, f"Période {mois} soumise et verrouillée.")
    return redirect("spe_report:period_detail", mois_id=mois.id)


@login_required
@permission_required("spe_report.reopen_periode", raise_exception=True)
def period_reopen(request, mois_id):
    mois = get_object_or_404(Mois, pk=mois_id)
    periode = get_object_or_404(PeriodeRapport, mois=mois)
    if request.method == "POST":
        periode.statut = PeriodeRapport.STATUT_BROUILLON
        periode.save()
        messages.warning(request, f"Période {mois} rouverte pour modification.")
    return redirect("spe_report:period_detail", mois_id=mois.id)


def _save_mesure_row(mois, row, cleaned_data, user):
    ligne = row["ligne"]
    type_participation = row["type_participation"]
    mesure, created = Mesure.objects.get_or_create(
        ligne_mesure=ligne, mois=mois, type_participation=type_participation
    )
    previous = None if created else snapshot_before(mesure)
    for suffix, boundfield in row["fields"].items():
        setattr(mesure, MESURE_FIELD_MAP[suffix], cleaned_data.get(boundfield.name))
    if created:
        mesure.created_by = user
    mesure.save()
    record_change(
        mesure, ChangeLog.ACTION_CREATE if created else ChangeLog.ACTION_UPDATE, user, previous
    )


def _save_mesure_totals(mois, section, user):
    ligne_ids = {row["ligne"].id: row["ligne"] for row in section["rows"] if row["has_breakdown"]}
    for ligne_id, ligne in ligne_ids.items():
        agg = Mesure.objects.filter(
            ligne_mesure=ligne, mois=mois, type_participation__isnull=False
        ).aggregate(**{field: Sum(field) for field in MESURE_SUM_FIELDS})
        mesure, created = Mesure.objects.get_or_create(
            ligne_mesure=ligne, mois=mois, type_participation=None
        )
        previous = None if created else snapshot_before(mesure)
        for field, value in agg.items():
            setattr(mesure, field, value)
        if created:
            mesure.created_by = user
        mesure.save()
        record_change(
            mesure, ChangeLog.ACTION_CREATE if created else ChangeLog.ACTION_UPDATE, user, previous
        )


@login_required
def period_section(request, mois_id, code):
    mois = get_object_or_404(Mois, pk=mois_id)
    rapport = get_object_or_404(Rapport, code=code)
    periode, _ = PeriodeRapport.objects.get_or_create(mois=mois)

    if request.method == "POST":
        if periode.est_verrouillee:
            messages.error(
                request, "Cette période est soumise et verrouillée. Rouvrez-la pour la modifier."
            )
            return redirect("spe_report:period_detail", mois_id=mois.id)

        form, sections = build_section_form(rapport, mois, data=request.POST)
        if form.is_valid():
            with transaction.atomic():
                for section in sections:
                    for row in section["rows"]:
                        if not row["is_total"]:
                            _save_mesure_row(mois, row, form.cleaned_data, request.user)
                    _save_mesure_totals(mois, section, request.user)
            messages.success(request, f"Section « {rapport.libelle} » enregistrée.")
            return redirect("spe_report:period_detail", mois_id=mois.id)
    else:
        form, sections = build_section_form(rapport, mois)

    return render(
        request,
        "spe_report/period_section.html",
        {
            "mois": mois,
            "rapport": rapport,
            "periode": periode,
            "form": form,
            "sections": sections,
        },
    )


def _save_emploi(mois, rows, cleaned_data, user):
    for row in rows:
        categorie = row["categorie"]
        effectif, created = Effectif.objects.get_or_create(categorie=categorie, mois=mois)
        previous = None if created else snapshot_before(effectif)
        effectif.valeur = cleaned_data.get(row["fields"]["valeur"].name)
        effectif.valeur_n1 = cleaned_data.get(row["fields"]["valeur_n1"].name)
        if created:
            effectif.created_by = user
        effectif.save()
        record_change(effectif, ChangeLog.ACTION_CREATE if created else ChangeLog.ACTION_UPDATE, user, previous)

        if "dont_fields" in row:
            dont, dont_created = DontEffectif.objects.get_or_create(categorie=categorie, mois=mois)
            previous = None if dont_created else snapshot_before(dont)
            dont.valeur = cleaned_data.get(row["dont_fields"]["valeur"].name)
            dont.valeur_n1 = cleaned_data.get(row["dont_fields"]["valeur_n1"].name)
            if dont_created:
                dont.created_by = user
            dont.save()
            record_change(
                dont, ChangeLog.ACTION_CREATE if dont_created else ChangeLog.ACTION_UPDATE, user, previous
            )


@login_required
def period_emploi(request, mois_id):
    mois = get_object_or_404(Mois, pk=mois_id)
    periode, _ = PeriodeRapport.objects.get_or_create(mois=mois)

    if request.method == "POST":
        if periode.est_verrouillee:
            messages.error(
                request, "Cette période est soumise et verrouillée. Rouvrez-la pour la modifier."
            )
            return redirect("spe_report:period_detail", mois_id=mois.id)
        form, rows = build_emploi_form(mois, data=request.POST)
        if form.is_valid():
            with transaction.atomic():
                _save_emploi(mois, rows, form.cleaned_data, request.user)
            messages.success(request, "Section « Emploi » enregistrée.")
            return redirect("spe_report:period_detail", mois_id=mois.id)
    else:
        form, rows = build_emploi_form(mois)

    return render(
        request,
        "spe_report/period_emploi.html",
        {"mois": mois, "periode": periode, "form": form, "rows": rows},
    )


def _save_investissements(mois, sections, cleaned_data, user):
    for section in sections:
        structure = section["structure"]
        for row in section["rows"]:
            if row["is_total"]:
                continue
            action = row["action"]
            montant, created = MontantInvestissement.objects.get_or_create(
                mois=mois, structure=structure, action=action
            )
            previous = None if created else snapshot_before(montant)
            montant.valeur_realisation = cleaned_data.get(row["fields"]["real"].name)
            montant.valeur_objectif_revise = cleaned_data.get(row["fields"]["objectif"].name)
            if created:
                montant.created_by = user
            montant.save()
            record_change(
                montant, ChangeLog.ACTION_CREATE if created else ChangeLog.ACTION_UPDATE, user, previous
            )

        if structure.actions.exists():
            agg = MontantInvestissement.objects.filter(
                mois=mois, structure=structure, action__isnull=False
            ).aggregate(
                valeur_realisation=Sum("valeur_realisation"),
                valeur_objectif_revise=Sum("valeur_objectif_revise"),
            )
            total, created = MontantInvestissement.objects.get_or_create(
                mois=mois, structure=structure, action=None
            )
            previous = None if created else snapshot_before(total)
            total.valeur_realisation = agg["valeur_realisation"]
            total.valeur_objectif_revise = agg["valeur_objectif_revise"]
            if created:
                total.created_by = user
            total.save()
            record_change(
                total, ChangeLog.ACTION_CREATE if created else ChangeLog.ACTION_UPDATE, user, previous
            )


@login_required
def period_investissements(request, mois_id):
    mois = get_object_or_404(Mois, pk=mois_id)
    periode, _ = PeriodeRapport.objects.get_or_create(mois=mois)

    if request.method == "POST":
        if periode.est_verrouillee:
            messages.error(
                request, "Cette période est soumise et verrouillée. Rouvrez-la pour la modifier."
            )
            return redirect("spe_report:period_detail", mois_id=mois.id)
        form, sections = build_investissement_form(mois, data=request.POST)
        if form.is_valid():
            with transaction.atomic():
                _save_investissements(mois, sections, form.cleaned_data, request.user)
            messages.success(request, "Section « Investissements » enregistrée.")
            return redirect("spe_report:period_detail", mois_id=mois.id)
    else:
        form, sections = build_investissement_form(mois)

    return render(
        request,
        "spe_report/period_investissements.html",
        {"mois": mois, "periode": periode, "form": form, "sections": sections},
    )


@login_required
def objectifs(request, annee):
    if request.method == "POST":
        form, sections = build_objectifs_form(annee, data=request.POST)
        if form.is_valid():
            with transaction.atomic():
                for section in sections:
                    for row in section["rows"]:
                        ligne = row["ligne"]
                        value = form.cleaned_data.get(row["field"].name)
                        objectif, created = Objectif.objects.get_or_create(ligne_mesure=ligne, annee=annee)
                        previous = None if created else snapshot_before(objectif)
                        objectif.valeur = value
                        if created:
                            objectif.created_by = request.user
                        objectif.save()
                        record_change(
                            objectif,
                            ChangeLog.ACTION_CREATE if created else ChangeLog.ACTION_UPDATE,
                            request.user,
                            previous,
                        )
            messages.success(request, f"Objectifs {annee} enregistrés.")
            return redirect("spe_report:objectifs", annee=annee)
    else:
        form, sections = build_objectifs_form(annee)

    return render(
        request, "spe_report/objectifs.html", {"annee": annee, "form": form, "sections": sections}
    )


def _ratio(numerator, denominator):
    if numerator is None or not denominator:
        return None
    return numerator / denominator


def _evolution(numerator, denominator):
    ratio = _ratio(numerator, denominator)
    return ratio - 1 if ratio is not None else None


@login_required
def period_report(request, mois_id):
    mois = get_object_or_404(Mois, pk=mois_id)
    sections = []
    for rapport in Rapport.objects.order_by("ordre"):
        lignes = (
            LigneMesure.objects.filter(master_entite__rapport=rapport)
            .select_related("master_entite", "unite_mesure")
            .order_by("master_entite__ordre", "ordre")
        )
        mesures = {
            m.ligne_mesure_id: m
            for m in Mesure.objects.filter(
                ligne_mesure__in=lignes, mois=mois, type_participation__isnull=True
            )
        }
        rows = []
        for ligne in lignes:
            m = mesures.get(ligne.id)
            rows.append(
                {
                    "ligne": ligne,
                    "mesure": m,
                    "taux_mois": _ratio(getattr(m, "valeur_realisation", None), getattr(m, "valeur_previsionnel", None)),
                    "taux_cumul": _ratio(
                        getattr(m, "valeur_realisation_cumul", None), getattr(m, "valeur_previsionnel_cumul", None)
                    ),
                    "evolution_mois": _evolution(
                        getattr(m, "valeur_realisation", None), getattr(m, "valeur_realisation_n1", None)
                    ),
                    "evolution_cumul": _evolution(
                        getattr(m, "valeur_realisation_cumul", None), getattr(m, "valeur_realisation_cumul_n1", None)
                    ),
                }
            )
        sections.append({"rapport": rapport, "rows": rows})

    emploi_rows = []
    for categorie in Categorie.objects.select_related("master_categorie").order_by("ordre"):
        effectif = Effectif.objects.filter(categorie=categorie, mois=mois).first()
        dont = DontEffectif.objects.filter(categorie=categorie, mois=mois).first()
        emploi_rows.append(
            {
                "categorie": categorie,
                "effectif": effectif,
                "dont": dont,
                "evolution": _evolution(
                    getattr(effectif, "valeur", None), getattr(effectif, "valeur_n1", None)
                ),
            }
        )

    invest_sections = []
    for structure in Structure.objects.prefetch_related("actions").order_by("ordre"):
        rows = []
        for action in structure.actions.order_by("ordre"):
            m = MontantInvestissement.objects.filter(mois=mois, structure=structure, action=action).first()
            rows.append(
                {
                    "action": action,
                    "montant": m,
                    "taux": _ratio(
                        getattr(m, "valeur_realisation", None), getattr(m, "valeur_objectif_revise", None)
                    ),
                }
            )
        total = MontantInvestissement.objects.filter(mois=mois, structure=structure, action__isnull=True).first()
        invest_sections.append(
            {
                "structure": structure,
                "rows": rows,
                "total": total,
                "taux_total": _ratio(
                    getattr(total, "valeur_realisation", None), getattr(total, "valeur_objectif_revise", None)
                ),
            }
        )

    return render(
        request,
        "spe_report/period_report.html",
        {"mois": mois, "sections": sections, "emploi_rows": emploi_rows, "invest_sections": invest_sections},
    )
