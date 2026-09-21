import random
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from spe_report.forms import (
    build_emploi_form,
    build_investissement_form,
    build_section_form,
)
from spe_report.models import Mois, PeriodeRapport, Rapport
from spe_report.views import (
    _save_emploi,
    _save_investissements,
    _save_mesure_row,
    _save_mesure_totals,
)


class Command(BaseCommand):
    help = (
        "DEMO/TESTING ONLY. Fills every section of a reporting period with random "
        "placeholder numbers so the entry flow can be exercised end-to-end. "
        "Never use this for a period meant to hold real report figures."
    )

    def add_arguments(self, parser):
        parser.add_argument("numero", type=int)
        parser.add_argument("annee", type=int)
        parser.add_argument("--username", default=None, help="User to attribute the entries to (default: any superuser).")
        parser.add_argument("--seed", type=int, default=None, help="Random seed, for reproducible fake data.")

    def handle(self, *args, **options):
        try:
            mois = Mois.objects.get(numero=options["numero"], annee=options["annee"])
        except Mois.DoesNotExist:
            raise CommandError("That period doesn't exist yet — create it first.")

        periode, _ = PeriodeRapport.objects.get_or_create(mois=mois)
        if periode.est_verrouillee:
            raise CommandError("This period is submitted/locked. Reopen it first.")

        User = get_user_model()
        if options["username"]:
            user = User.objects.get(username=options["username"])
        else:
            user = User.objects.filter(is_superuser=True).first()
            if user is None:
                raise CommandError("No superuser found; pass --username.")

        rng = random.Random(options["seed"])

        with transaction.atomic():
            for rapport in Rapport.objects.all():
                self._fill_section(rapport, mois, user, rng)
            self._fill_emploi(mois, user, rng)
            self._fill_investissements(mois, user, rng)

        self.stdout.write(self.style.SUCCESS(f"Filled {mois} with placeholder test data (attributed to {user})."))
        self.stdout.write(self.style.WARNING("These are random numbers, not real report figures."))

    def _fill_section(self, rapport, mois, user, rng):
        form, sections = build_section_form(rapport, mois)
        data = {name: str(rng.randint(50, 500)) for name in form.fields}
        form, sections = build_section_form(rapport, mois, data=data)
        if not form.is_valid():
            raise CommandError(f"Generated data invalid for {rapport.code}: {form.errors}")
        for section in sections:
            for row in section["rows"]:
                if not row["is_total"]:
                    _save_mesure_row(mois, row, form.cleaned_data, user)
            _save_mesure_totals(mois, section, user)

    def _fill_emploi(self, mois, user, rng):
        form, rows = build_emploi_form(mois)
        data = {name: str(rng.randint(20, 400)) for name in form.fields}
        form, rows = build_emploi_form(mois, data=data)
        if not form.is_valid():
            raise CommandError(f"Generated data invalid for Emploi: {form.errors}")
        _save_emploi(mois, rows, form.cleaned_data, user)

    def _fill_investissements(self, mois, user, rng):
        form, sections = build_investissement_form(mois)
        data = {name: str(rng.randint(10, 300)) for name in form.fields}
        form, sections = build_investissement_form(mois, data=data)
        if not form.is_valid():
            raise CommandError(f"Generated data invalid for Investissements: {form.errors}")
        _save_investissements(mois, sections, form.cleaned_data, user)
