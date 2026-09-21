import re
import unicodedata

import openpyxl
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from spe_report.models import (
    Action,
    Categorie,
    LigneMesure,
    LigneMesureParticipation,
    MasterCategorie,
    MasterEntite,
    Rapport,
    Structure,
    TypeParticipation,
    UniteMesure,
)

# One entry per report sheet that follows the generic LigneMesure/Mesure shape.
# `sheet` must match the workbook's sheet name exactly (openpyxl keeps trailing
# spaces some of these sheets have in the source file).
SHEET_CONFIGS = [
    {"sheet": "Forages  ", "code": "forages", "libelle": "Forages", "utilise_previsionnel": True},
    {"sheet": "Production", "code": "production", "libelle": "Production", "utilise_previsionnel": True},
    {"sheet": "TRC", "code": "trc", "libelle": "Transport par Canalisations", "utilise_previsionnel": True},
    {"sheet": "LQS", "code": "lqs", "libelle": "Liquéfaction et Séparation (GNL/GPL)", "utilise_previsionnel": True},
    {"sheet": "Raffinage", "code": "raffinage", "libelle": "Raffinage", "utilise_previsionnel": True},
    {"sheet": "Pétrochimie", "code": "petrochimie", "libelle": "Pétrochimie", "utilise_previsionnel": True},
    {"sheet": "Export Vol", "code": "export_vol", "libelle": "Export - Volumes", "utilise_previsionnel": True},
    {
        "sheet": "Export Val", "code": "export_val", "libelle": "Export - Valeurs",
        "utilise_previsionnel": False,
        # This sheet reports everything in "Millions Dollars" with no per-line
        # unit column, so the usual "no unit => section header" heuristic
        # can't be used here: every row is a measured line.
        "has_units": False,
    },
    {"sheet": "MN Vol", "code": "mn_vol", "libelle": "Marché National - Volumes", "utilise_previsionnel": True},
    {"sheet": "MN Val", "code": "mn_val", "libelle": "Marché National - Valeurs", "utilise_previsionnel": True},
    {"sheet": "PR Vol", "code": "pr_vol", "libelle": "Produits Raffinés - Volumes des ventes", "utilise_previsionnel": True},
]

LABEL_COL = 2  # column B
UNIT_COL = 4  # column D

# Known TypeParticipation breakdown labels -> canonical libelle. Matched after
# lowercasing/accent-folding, so "En Effort propre", "en effort propre" and
# "EN EFFORT PROPRE" all match the same alias.
PARTICIPATION_ALIASES = {
    "en effort propre": "En Effort propre",
    "en association": "En Association / Partenariat",
    "en association / partenariat": "En Association / Partenariat",
    "sonatrach seule": "Sonatrach Seule",
    "associes": "Associés",
    "associe": "Associés",
    # Export Vol/Val each break one "(Export) Butane/Propane" line down by
    # product rather than by ownership — same shape (a total + breakdown
    # rows), just a different breakdown dimension, so it reuses the same
    # TypeParticipation mechanism instead of a bespoke concept.
    "butane": "Butane",
    "propane": "Propane",
}

# A line whose label collapses to exactly this (no distinguishing prefix) is
# the standalone Butane/Propane family total, seen elsewhere in the workbook
# as "Export Butane /Propane" (Export Vol) — canonicalize to that same name
# so it doesn't render identically to the unrelated "Butane / Propane" line
# under "Produits Raffinés" (broken down by ownership, not by product).
BUTANE_PROPANE_TOTAL_KEY = "butane/propane"
BUTANE_PROPANE_CANONICAL_LABEL = "Export Butane / Propane"

# Hand-modeled catalog for the two sheets that don't use the LigneMesure
# shape at all (see the plan: they map to Structure/Action and
# MasterCategorie/Categorie instead). These are short, stable lists, not
# worth auto-detecting from ambiguous cell layout.
INVESTISSEMENT_STRUCTURES = [
    ("Activité E & P", [
        "Exploration en effort propre",
        "Exploration en partenariat",
        "Dévelop. & Exploit. des gisements en effort propre",
        "Dévelop. & Exploit. des gisements en association",
        "Structures de Soutien (FOR & AST & Laboratoire)",
    ]),
    ("Activité TRC", [
        "Développement & Réhabilitation",
        "Exploitation & Gestion Réseau",
        "Autres (Maintenance, Télécommunication & Siège)",
    ]),
    ("Activité LQS", [
        "Développement",
        "Maintien, Fiabilité et Sécurité Division GNL & GPL",
        "Autres (Infrastructures, zones industrielles, siège)",
    ]),
    ("Activité RPC", [
        "Développement Raffinage",
        "Développement Pétrochimie",
        "Maintien fiabilité Sécurité",
        "Autres",
    ]),
    ("EPM", []),
    ("Autres Investissements", []),
]

# (categorie_libelle, dont_libelle_or_None)
EMPLOI_CATEGORIES = [
    ("Permanents", None),
    ("Ingénieurs +", None),
    ("Cadres Universitaires", None),
    ("Autres Cadres", None),
    ("Total Cadres", "dont Cadres Sup."),
    ("Maîtrise", "dont T. Supérieurs"),
    ("Exécution", None),
    ("Temporaires", "dont Sûreté"),
    ("Effectif Total", None),
]


def normalize(label):
    text = unicodedata.normalize("NFKD", label or "").encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", text).strip().lower()


def resolve_merged(ws, row, col):
    """Return the effective value of a cell, forward-filling vertically merged ranges."""
    cell = ws.cell(row=row, column=col)
    if cell.value is not None:
        return cell.value
    for merged_range in ws.merged_cells.ranges:
        if (
            merged_range.min_col <= col <= merged_range.max_col
            and merged_range.min_row <= row <= merged_range.max_row
        ):
            return ws.cell(row=merged_range.min_row, column=merged_range.min_col).value
    return None


def find_header_last_row(ws, max_scan=12):
    for row in range(1, max_scan + 1):
        for col in range(1, ws.max_column + 1):
            value = ws.cell(row=row, column=col).value
            if isinstance(value, str) and value.strip() == "(1)":
                return row
    raise CommandError(f"Could not find the '(1)' header marker in sheet '{ws.title}'.")


def _next_labels_are_butane_propane(ws, row):
    """Whether the two rows right after `row` are the Butane/Propane breakdown.

    Distinguishes the standalone Butane/Propane total line (broken down into
    Butane and Propane) from the differently-shaped "Butane/Propane" line
    under "Produits Raffinés" (broken down by Sonatrach Seule / Associés
    instead) — both happen to share almost the same label text.
    """
    next_labels = []
    for peek_row in range(row + 1, row + 3):
        value = ws.cell(row=peek_row, column=LABEL_COL).value
        if value is not None and str(value).strip():
            next_labels.append(normalize(str(value).strip()))
    return next_labels[:2] == ["butane", "propane"]


class Command(BaseCommand):
    help = (
        "One-time seed of the SPE report catalog (Rapport/MasterEntite/LigneMesure/"
        "UniteMesure/TypeParticipation/Structure/Action/Categorie) from the reference "
        "'Tableau d'information type SPE.xlsx' workbook. Safe to re-run: existing rows "
        "are matched by natural key and left untouched."
    )

    def add_arguments(self, parser):
        parser.add_argument("workbook_path", help="Path to the SPE .xlsx reference workbook")

    def handle(self, *args, **options):
        wb = openpyxl.load_workbook(options["workbook_path"], data_only=True)

        with transaction.atomic():
            for config in SHEET_CONFIGS:
                if config["sheet"] not in wb.sheetnames:
                    raise CommandError(f"Sheet '{config['sheet']}' not found in workbook.")
                self._seed_mesure_sheet(wb[config["sheet"]], config)
            self._seed_investissements()
            self._seed_emploi()

        self.stdout.write(self.style.SUCCESS("SPE catalog seeded."))

    def _seed_mesure_sheet(self, ws, config):
        rapport, _ = Rapport.objects.update_or_create(
            code=config["code"],
            defaults={"libelle": config["libelle"], "utilise_previsionnel": config["utilise_previsionnel"]},
        )

        header_last_row = find_header_last_row(ws)
        default_section, _ = MasterEntite.objects.get_or_create(
            rapport=rapport, libelle=config["libelle"], defaults={"ordre": 0}
        )

        current_section = default_section
        section_ordre = 0
        current_ligne = None
        ligne_ordre = 0

        # When a sheet has no per-line unit column, the header row's own label
        # (e.g. "En Millions Dollars") is a unit descriptor for the whole
        # sheet, not a data line — skip past it.
        start_row = header_last_row if config.get("has_units", True) else header_last_row + 1

        for row in range(start_row, ws.max_row + 1):
            raw_label = ws.cell(row=row, column=LABEL_COL).value
            if raw_label is None or not str(raw_label).strip():
                continue
            label = str(raw_label).strip()
            if label.startswith("(") or len(label) > 120:
                continue  # footnote row

            key = normalize(label)
            if key in PARTICIPATION_ALIASES:
                if current_ligne is None:
                    continue  # breakdown row with no parent line above it; skip defensively
                type_participation, _ = TypeParticipation.objects.get_or_create(
                    libelle=PARTICIPATION_ALIASES[key]
                )
                LigneMesureParticipation.objects.get_or_create(
                    ligne_mesure=current_ligne,
                    type_participation=type_participation,
                    defaults={"ordre": current_ligne.types_participation.count()},
                )
                continue

            if key.replace(" ", "").endswith(BUTANE_PROPANE_TOTAL_KEY) and _next_labels_are_butane_propane(
                ws, row
            ):
                # There are two unrelated "Butane/Propane" lines in this
                # workbook: one broken down by ownership (Sonatrach Seule /
                # Associés, under "Produits Raffinés") and one broken down by
                # product (Butane / Propane themselves). Only the latter gets
                # canonicalized — and canonicalized *before* the
                # get_or_create below, not after, so a re-run looks up the
                # same row it created last time instead of recreating the
                # pre-rename label.
                label = BUTANE_PROPANE_CANONICAL_LABEL

            unit_value = resolve_merged(ws, row, UNIT_COL) if config.get("has_units", True) else "n/a"
            if unit_value is None:
                # No unit on this row or anything it inherits from a merge:
                # it's a new section header, not a measurable line.
                section_ordre += 1
                current_section, _ = MasterEntite.objects.get_or_create(
                    rapport=rapport, libelle=label, defaults={"ordre": section_ordre}
                )
                current_ligne = None
                continue

            unite_mesure = None
            if config.get("has_units", True):
                unite_mesure, _ = UniteMesure.objects.get_or_create(libelle=str(unit_value).strip())
            ligne_ordre += 1
            current_ligne, _ = LigneMesure.objects.get_or_create(
                master_entite=current_section,
                libelle=label,
                defaults={"unite_mesure": unite_mesure, "ordre": ligne_ordre},
            )

    def _seed_investissements(self):
        for structure_ordre, (structure_label, action_labels) in enumerate(INVESTISSEMENT_STRUCTURES, start=1):
            structure, _ = Structure.objects.get_or_create(
                libelle=structure_label, defaults={"ordre": structure_ordre}
            )
            for action_ordre, action_label in enumerate(action_labels, start=1):
                Action.objects.get_or_create(
                    structure=structure, libelle=action_label, defaults={"ordre": action_ordre}
                )

    def _seed_emploi(self):
        master_categorie, _ = MasterCategorie.objects.get_or_create(
            libelle="Effectifs", defaults={"ordre": 1}
        )
        for ordre, (categorie_label, dont_label) in enumerate(EMPLOI_CATEGORIES, start=1):
            Categorie.objects.get_or_create(
                libelle=categorie_label,
                defaults={
                    "master_categorie": master_categorie,
                    "ordre": ordre,
                    "dont_libelle": dont_label or "",
                },
            )
