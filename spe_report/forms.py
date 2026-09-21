from django import forms
from django.db.models import Sum

from .models import (
    Categorie,
    DontEffectif,
    Effectif,
    LigneMesure,
    Mesure,
    Mois,
    MontantInvestissement,
    Objectif,
    Structure,
)

DECIMAL_WIDGET_ATTRS = {"class": "form-control form-control-sm text-end", "step": "any"}


class NewPeriodForm(forms.Form):
    numero = forms.TypedChoiceField(
        choices=[(i, Mois(numero=i, annee=2000).libelle.split(" ")[0]) for i in range(1, 13)],
        coerce=int,
        widget=forms.Select(attrs={"class": "form-select"}),
        label="Mois",
    )
    annee = forms.IntegerField(
        min_value=2000, max_value=2100, widget=forms.NumberInput(attrs={"class": "form-control"}), label="Année"
    )

    def clean(self):
        cleaned = super().clean()
        numero = cleaned.get("numero")
        annee = cleaned.get("annee")
        if numero and annee and Mois.objects.filter(numero=numero, annee=annee).exists():
            raise forms.ValidationError("Cette période existe déjà.")
        return cleaned


def _field_name(ligne_id, type_participation_id, suffix):
    return f"m_{ligne_id}_{type_participation_id or 0}_{suffix}"


def _decimal_field(label, required=False, initial=None):
    return forms.DecimalField(
        label=label,
        required=required,
        initial=initial,
        max_digits=18,
        decimal_places=2,
        widget=forms.NumberInput(attrs=DECIMAL_WIDGET_ATTRS),
    )


def _lookup(mesures_by_key, ligne_id, type_participation_id, attr):
    mesure = mesures_by_key.get((ligne_id, type_participation_id))
    return getattr(mesure, attr) if mesure else None


def build_section_form(rapport, mois, data=None):
    """Build the entry form + a display layout for one report section (Rapport) / month.

    Returns (form, sections) where `sections` is a list of
    {"master_entite": MasterEntite, "rows": [row, ...]} for template rendering.
    Each row is a dict describing either a plain line or one slot of a
    TypeParticipation breakdown, with the field names to render and the
    already-known (read-only-ish, but editable) N-1 / cumul suggestions.
    """
    mois_n1 = mois.mois_n1()
    mois_precedents = mois.mois_precedents_annee().exclude(pk=mois.pk)

    lignes = list(
        LigneMesure.objects.filter(master_entite__rapport=rapport)
        .select_related("master_entite", "unite_mesure")
        .prefetch_related("participations__type_participation")
        .order_by("master_entite__ordre", "master_entite_id", "ordre")
    )
    ligne_ids = [l.id for l in lignes]

    current_mesures = Mesure.objects.filter(ligne_mesure_id__in=ligne_ids, mois=mois)
    current_by_key = {(m.ligne_mesure_id, m.type_participation_id): m for m in current_mesures}

    n1_mesures = Mesure.objects.filter(ligne_mesure_id__in=ligne_ids, mois=mois_n1) if mois_n1 else []
    n1_by_key = {(m.ligne_mesure_id, m.type_participation_id): m for m in n1_mesures}

    cumul_prev_year = (
        Mesure.objects.filter(ligne_mesure_id__in=ligne_ids, mois__in=mois_precedents)
        .values("ligne_mesure_id", "type_participation_id")
        .annotate(real=Sum("valeur_realisation"), prev=Sum("valeur_previsionnel"))
    )
    cumul_by_key = {(r["ligne_mesure_id"], r["type_participation_id"]): r for r in cumul_prev_year}

    n1_mois_precedents = mois_n1.mois_precedents_annee() if mois_n1 else Mois.objects.none()
    cumul_n1 = (
        Mesure.objects.filter(ligne_mesure_id__in=ligne_ids, mois__in=n1_mois_precedents)
        .values("ligne_mesure_id", "type_participation_id")
        .annotate(real=Sum("valeur_realisation"))
    ) if mois_n1 else []
    cumul_n1_by_key = {(r["ligne_mesure_id"], r["type_participation_id"]): r for r in cumul_n1}

    form = forms.Form(data)
    sections = []
    sections_by_id = {}

    for ligne in lignes:
        section = sections_by_id.get(ligne.master_entite_id)
        if section is None:
            section = {"master_entite": ligne.master_entite, "rows": []}
            sections_by_id[ligne.master_entite_id] = section
            sections.append(section)

        slots = list(ligne.participations.all())
        has_breakdown = bool(slots)
        slot_keys = [(sp.type_participation_id, sp.type_participation) for sp in slots] or [(None, None)]

        for type_participation_id, type_participation in slot_keys:
            key = (ligne.id, type_participation_id)
            field_names = {}

            def add(suffix, label, lookup_source, lookup_attr):
                name = _field_name(ligne.id, type_participation_id, suffix)
                initial = _lookup(lookup_source, ligne.id, type_participation_id, lookup_attr) if lookup_source else None
                form.fields[name] = _decimal_field(label, initial=initial)
                field_names[suffix] = name

            if rapport.utilise_previsionnel:
                add("prev", "Prévision", current_by_key, "valeur_previsionnel")
            add("real", "Réalisation", current_by_key, "valeur_realisation")

            realn1_name = _field_name(ligne.id, type_participation_id, "realn1")
            form.fields[realn1_name] = _decimal_field(
                "Réalisation N-1", initial=_lookup(n1_by_key, ligne.id, type_participation_id, "valeur_realisation")
            )
            field_names["realn1"] = realn1_name

            prior_real = cumul_by_key.get(key, {}).get("real")
            prior_prev = cumul_by_key.get(key, {}).get("prev")
            prior_realn1 = cumul_n1_by_key.get(key, {}).get("real")

            if rapport.utilise_previsionnel:
                name = _field_name(ligne.id, type_participation_id, "cumulprev")
                form.fields[name] = _decimal_field("Cumul Prévision", initial=prior_prev)
                field_names["cumulprev"] = name

            name = _field_name(ligne.id, type_participation_id, "cumulreal")
            form.fields[name] = _decimal_field("Cumul Réalisation", initial=prior_real)
            field_names["cumulreal"] = name

            name = _field_name(ligne.id, type_participation_id, "cumulrealn1")
            form.fields[name] = _decimal_field("Cumul Réalisation N-1", initial=prior_realn1)
            field_names["cumulrealn1"] = name

            section["rows"].append(
                {
                    "ligne": ligne,
                    "type_participation": type_participation,
                    "is_total": False,
                    "has_breakdown": has_breakdown,
                    "unite": ligne.unite_mesure,
                    "fields": {suffix: form[name] for suffix, name in field_names.items()},
                    "prior_cumul_real": prior_real or 0,
                    "prior_cumul_prev": prior_prev or 0,
                }
            )

        if has_breakdown:
            total = current_by_key.get((ligne.id, None))
            section["rows"].append(
                {
                    "ligne": ligne,
                    "type_participation": None,
                    "is_total": True,
                    "has_breakdown": True,
                    "unite": ligne.unite_mesure,
                    "current": total,
                }
            )

    return form, sections


def build_emploi_form(mois, data=None):
    """Entry form for the Emploi sheet: Effectif per Categorie (+ DontEffectif when it has one)."""
    mois_n1 = mois.mois_n1()
    categories = list(Categorie.objects.select_related("master_categorie").order_by("ordre", "libelle"))

    effectifs = {e.categorie_id: e for e in Effectif.objects.filter(mois=mois)}
    donts = {d.categorie_id: d for d in DontEffectif.objects.filter(mois=mois)}
    effectifs_n1 = {e.categorie_id: e for e in Effectif.objects.filter(mois=mois_n1)} if mois_n1 else {}
    donts_n1 = {d.categorie_id: d for d in DontEffectif.objects.filter(mois=mois_n1)} if mois_n1 else {}

    form = forms.Form(data)
    rows = []
    for categorie in categories:
        valeur_name = f"eff_{categorie.id}_valeur"
        valeur_n1_name = f"eff_{categorie.id}_valeur_n1"
        form.fields[valeur_name] = _decimal_field(
            "Situation fin de mois", initial=getattr(effectifs.get(categorie.id), "valeur", None)
        )
        form.fields[valeur_n1_name] = _decimal_field(
            "Situation N-1",
            initial=(
                getattr(effectifs_n1.get(categorie.id), "valeur", None)
                if mois_n1
                else None
            ),
        )
        row = {
            "categorie": categorie,
            "fields": {"valeur": form[valeur_name], "valeur_n1": form[valeur_n1_name]},
        }
        if categorie.dont_libelle:
            dv_name = f"dont_{categorie.id}_valeur"
            dv_n1_name = f"dont_{categorie.id}_valeur_n1"
            form.fields[dv_name] = _decimal_field(
                categorie.dont_libelle, initial=getattr(donts.get(categorie.id), "valeur", None)
            )
            form.fields[dv_n1_name] = _decimal_field(
                f"{categorie.dont_libelle} N-1",
                initial=getattr(donts_n1.get(categorie.id), "valeur", None) if mois_n1 else None,
            )
            row["dont_fields"] = {"valeur": form[dv_name], "valeur_n1": form[dv_n1_name]}
        rows.append(row)

    return form, rows


def build_investissement_form(mois, data=None):
    """Entry form for the Investissements sheet: MontantInvestissement per Structure/Action."""
    structures = list(Structure.objects.prefetch_related("actions").order_by("ordre", "libelle"))
    montants = {
        (m.structure_id, m.action_id): m
        for m in MontantInvestissement.objects.filter(mois=mois)
    }

    form = forms.Form(data)
    sections = []
    for structure in structures:
        actions = list(structure.actions.order_by("ordre", "libelle"))
        rows = []
        for action in actions:
            key = (structure.id, action.id)
            real_name = f"inv_{structure.id}_{action.id}_real"
            obj_name = f"inv_{structure.id}_{action.id}_objectif"
            form.fields[real_name] = _decimal_field(
                "Réalisation", initial=getattr(montants.get(key), "valeur_realisation", None)
            )
            form.fields[obj_name] = _decimal_field(
                "Objectif révisé", initial=getattr(montants.get(key), "valeur_objectif_revise", None)
            )
            rows.append(
                {
                    "action": action,
                    "is_total": False,
                    "fields": {"real": form[real_name], "objectif": form[obj_name]},
                }
            )
        if actions:
            total = montants.get((structure.id, None))
            rows.append({"action": None, "is_total": True, "current": total})
        else:
            key = (structure.id, None)
            real_name = f"inv_{structure.id}_0_real"
            obj_name = f"inv_{structure.id}_0_objectif"
            form.fields[real_name] = _decimal_field(
                "Réalisation", initial=getattr(montants.get(key), "valeur_realisation", None)
            )
            form.fields[obj_name] = _decimal_field(
                "Objectif révisé", initial=getattr(montants.get(key), "valeur_objectif_revise", None)
            )
            rows.append(
                {
                    "action": None,
                    "is_total": False,
                    "fields": {"real": form[real_name], "objectif": form[obj_name]},
                }
            )
        sections.append({"structure": structure, "rows": rows})

    return form, sections


def build_objectifs_form(annee, data=None):
    """Entry form for annual objectives (one value per LigneMesure, set once a year)."""
    lignes = (
        LigneMesure.objects.select_related("master_entite__rapport", "unite_mesure")
        .order_by("master_entite__rapport__ordre", "master_entite__ordre", "ordre")
    )
    objectifs = {o.ligne_mesure_id: o for o in Objectif.objects.filter(annee=annee)}

    form = forms.Form(data)
    sections = []
    current_rapport_id = None
    for ligne in lignes:
        rapport = ligne.master_entite.rapport
        if rapport.id != current_rapport_id:
            sections.append({"rapport": rapport, "rows": []})
            current_rapport_id = rapport.id
        name = f"obj_{ligne.id}"
        form.fields[name] = _decimal_field(
            ligne.libelle, initial=getattr(objectifs.get(ligne.id), "valeur", None)
        )
        sections[-1]["rows"].append({"ligne": ligne, "field": form[name]})

    return form, sections
