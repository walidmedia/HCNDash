from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .models import (
    ChangeLog,
    LigneMesure,
    Mesure,
    Mois,
    PeriodeRapport,
    Rapport,
    TypeParticipation,
    UniteMesure,
)


def _make_catalog():
    from .models import LigneMesureParticipation, MasterEntite

    rapport = Rapport.objects.create(code="forages", libelle="Forages", ordre=1, utilise_previsionnel=True)
    section = MasterEntite.objects.create(rapport=rapport, libelle="Forage d'exploration", ordre=1)
    unite = UniteMesure.objects.create(libelle="Km Profil")

    ligne_breakdown = LigneMesure.objects.create(
        master_entite=section, libelle="Sismique 2D", unite_mesure=unite, ordre=1
    )
    effort_propre = TypeParticipation.objects.create(libelle="En Effort propre")
    association = TypeParticipation.objects.create(libelle="En Association / Partenariat")
    LigneMesureParticipation.objects.create(ligne_mesure=ligne_breakdown, type_participation=effort_propre, ordre=1)
    LigneMesureParticipation.objects.create(ligne_mesure=ligne_breakdown, type_participation=association, ordre=2)

    ligne_plain = LigneMesure.objects.create(
        master_entite=section, libelle="Puits terminés", unite_mesure=UniteMesure.objects.create(libelle="Nombre"), ordre=2
    )
    return rapport, ligne_breakdown, ligne_plain, [effort_propre, association]


class PeriodEntryTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user("alice", password="pw")
        self.superuser = User.objects.create_superuser("admin", "admin@example.com", "pw")
        self.rapport, self.ligne_breakdown, self.ligne_plain, self.participations = _make_catalog()
        self.mois = Mois.objects.create(numero=12, annee=2099)
        self.client.login(username="alice", password="pw")

    def _post_data(self):
        data = {}
        for tp in self.participations:
            prefix = f"m_{self.ligne_breakdown.id}_{tp.id}"
            data.update(
                {
                    f"{prefix}_prev": "10",
                    f"{prefix}_real": "12",
                    f"{prefix}_realn1": "9",
                    f"{prefix}_cumulprev": "100",
                    f"{prefix}_cumulreal": "110",
                    f"{prefix}_cumulrealn1": "90",
                }
            )
        prefix = f"m_{self.ligne_plain.id}_0"
        data.update(
            {
                f"{prefix}_prev": "5",
                f"{prefix}_real": "6",
                f"{prefix}_realn1": "4",
                f"{prefix}_cumulprev": "50",
                f"{prefix}_cumulreal": "60",
                f"{prefix}_cumulrealn1": "40",
            }
        )
        return data

    def test_period_list_and_create(self):
        resp = self.client.get(reverse("spe_report:period_list"))
        self.assertEqual(resp.status_code, 200)

        resp = self.client.post(reverse("spe_report:period_list"), {"numero": 1, "annee": 2098})
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(Mois.objects.filter(numero=1, annee=2098).exists())

    def test_duplicate_period_rejected(self):
        resp = self.client.post(
            reverse("spe_report:period_list"), {"numero": self.mois.numero, "annee": self.mois.annee}
        )
        self.assertEqual(resp.status_code, 200)  # form re-rendered with error
        self.assertContains(resp, "existe d")

    def test_section_save_computes_breakdown_total(self):
        resp = self.client.post(
            reverse("spe_report:period_section", args=[self.mois.id, self.rapport.code]),
            self._post_data(),
        )
        self.assertEqual(resp.status_code, 302)

        total = Mesure.objects.get(
            ligne_mesure=self.ligne_breakdown, mois=self.mois, type_participation=None
        )
        self.assertEqual(total.valeur_realisation, 24)  # 12 + 12
        self.assertEqual(total.valeur_previsionnel, 20)  # 10 + 10

        plain = Mesure.objects.get(ligne_mesure=self.ligne_plain, mois=self.mois, type_participation=None)
        self.assertEqual(plain.valeur_realisation, 6)

        self.assertTrue(ChangeLog.objects.filter(action=ChangeLog.ACTION_CREATE).exists())

    def test_locked_period_rejects_edits(self):
        self.client.post(
            reverse("spe_report:period_section", args=[self.mois.id, self.rapport.code]), self._post_data()
        )
        self.client.post(reverse("spe_report:period_submit", args=[self.mois.id]))

        periode = PeriodeRapport.objects.get(mois=self.mois)
        self.assertTrue(periode.est_verrouillee)

        data = self._post_data()
        prefix = f"m_{self.ligne_plain.id}_0"
        data[f"{prefix}_real"] = "999"
        self.client.post(
            reverse("spe_report:period_section", args=[self.mois.id, self.rapport.code]), data
        )
        plain = Mesure.objects.get(ligne_mesure=self.ligne_plain, mois=self.mois, type_participation=None)
        self.assertEqual(plain.valeur_realisation, 6)  # unchanged, edit was rejected

    def test_reopen_requires_admin_role(self):
        self.client.post(reverse("spe_report:period_submit", args=[self.mois.id]))

        resp = self.client.post(reverse("spe_report:period_reopen", args=[self.mois.id]))
        self.assertEqual(resp.status_code, 403)

        self.client.logout()
        self.client.login(username="admin", password="pw")
        resp = self.client.post(reverse("spe_report:period_reopen", args=[self.mois.id]))
        self.assertEqual(resp.status_code, 302)
        periode = PeriodeRapport.objects.get(mois=self.mois)
        self.assertFalse(periode.est_verrouillee)

    def test_delete_requires_admin_role(self):
        resp = self.client.post(reverse("spe_report:period_delete", args=[self.mois.id]))
        self.assertEqual(resp.status_code, 403)
        self.assertTrue(Mois.objects.filter(pk=self.mois.id).exists())

        self.client.logout()
        self.client.login(username="admin", password="pw")
        resp = self.client.post(reverse("spe_report:period_delete", args=[self.mois.id]))
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(Mois.objects.filter(pk=self.mois.id).exists())

    def test_export_xlsx_and_csv(self):
        self.client.post(
            reverse("spe_report:period_section", args=[self.mois.id, self.rapport.code]), self._post_data()
        )
        resp = self.client.get(reverse("spe_report:period_export", args=[self.mois.id, "xlsx"]))
        self.assertEqual(resp.status_code, 200)
        self.assertIn("spreadsheetml", resp["Content-Type"])

        resp = self.client.get(reverse("spe_report:period_export", args=[self.mois.id, "csv"]))
        self.assertEqual(resp.status_code, 200)
        self.assertIn("text/csv", resp["Content-Type"])

    def test_no_changelog_written_when_value_unchanged(self):
        self.client.post(
            reverse("spe_report:period_section", args=[self.mois.id, self.rapport.code]), self._post_data()
        )
        count_after_first_save = ChangeLog.objects.count()

        self.client.post(
            reverse("spe_report:period_section", args=[self.mois.id, self.rapport.code]), self._post_data()
        )
        self.assertEqual(ChangeLog.objects.count(), count_after_first_save)

    def test_report_and_other_sections_render(self):
        for name, args in [
            ("period_detail", [self.mois.id]),
            ("period_report", [self.mois.id]),
            ("period_emploi", [self.mois.id]),
            ("period_investissements", [self.mois.id]),
            ("objectifs", [self.mois.annee]),
        ]:
            resp = self.client.get(reverse(f"spe_report:{name}", args=args))
            self.assertEqual(resp.status_code, 200, f"{name} failed: {resp.status_code}")
