from unittest import mock

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

# period_submit() calls out to the real corporate Oracle server; tests mock it
# out so they stay fast and don't depend on that network being reachable.
_MOCK_ORACLE_PUSH = mock.patch("spe_report.views.push_period_to_oracle", return_value=(True, "ok"))


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

    @_MOCK_ORACLE_PUSH
    def test_locked_period_rejects_edits(self, mock_push):
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

    @_MOCK_ORACLE_PUSH
    def test_reopen_requires_admin_role(self, mock_push):
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

    @_MOCK_ORACLE_PUSH
    def test_submit_shows_oracle_success_message(self, mock_push):
        mock_push.return_value = (True, "Periode exportee avec succes vers Oracle (RAPPORT_SPE).")
        resp = self.client.post(
            reverse("spe_report:period_submit", args=[self.mois.id]), follow=True
        )
        mock_push.assert_called_once_with(self.mois)
        messages = [str(m) for m in resp.context["messages"]]
        self.assertTrue(any("Oracle" in m for m in messages))

    @_MOCK_ORACLE_PUSH
    def test_submit_shows_oracle_failure_warning_without_blocking_submission(self, mock_push):
        mock_push.return_value = (False, "Echec de l'import Oracle (statut=ERROR) : ORA-01400")
        resp = self.client.post(
            reverse("spe_report:period_submit", args=[self.mois.id]), follow=True
        )
        periode = PeriodeRapport.objects.get(mois=self.mois)
        self.assertTrue(periode.est_verrouillee)  # local submission still succeeds
        messages = [str(m) for m in resp.context["messages"]]
        self.assertTrue(any("échoué" in m and "ORA-01400" in m for m in messages))


class OracleExportPayloadTests(TestCase):
    """build_staging_payload() must match the JSON shape RAPPORT_SPE.PROCESS_STAGING parses."""

    def setUp(self):
        self.rapport, self.ligne_breakdown, self.ligne_plain, self.participations = _make_catalog()
        self.effort_propre, self.association = self.participations
        self.mois = Mois.objects.create(numero=3, annee=2099)

        Mesure.objects.create(
            ligne_mesure=self.ligne_breakdown, mois=self.mois, type_participation=None,
            valeur_previsionnel=20, valeur_realisation=24,
        )
        Mesure.objects.create(
            ligne_mesure=self.ligne_breakdown, mois=self.mois, type_participation=self.effort_propre,
            valeur_previsionnel=10, valeur_realisation=12,
        )
        Mesure.objects.create(
            ligne_mesure=self.ligne_plain, mois=self.mois, type_participation=None,
            valeur_previsionnel=5, valeur_realisation=6,
        )

    def test_payload_shape(self):
        from .oracle_export import build_staging_payload

        payload = build_staging_payload(self.mois)

        self.assertEqual(payload["periode"], {"mois": self.mois.libelle, "annee": 2099})

        sheet = payload["sheet_forages"]
        self.assertEqual(sheet["titre"], "Forages")
        self.assertEqual(len(sheet["data"]), 1)

        section = sheet["data"][0]
        self.assertEqual(section["title"], "Forage d'exploration")
        produits = {p["title"]: p for p in section["produits"]}

        breakdown = produits["Sismique 2D"]
        self.assertEqual(breakdown["mesure"], "Km Profil")
        self.assertEqual(breakdown["valeur_mesure_previsionnel"], 20.0)
        self.assertEqual(breakdown["valeur_mesure_realisation"], 24.0)
        type_titles = {t["title"] for t in breakdown["types"]}
        self.assertEqual(type_titles, {"En Effort propre", "En Association / Partenariat"})
        effort = next(t for t in breakdown["types"] if t["title"] == "En Effort propre")
        self.assertEqual(effort["valeur_mesure_previsionnel"], 10.0)

        plain = produits["Puits terminés"]
        self.assertEqual(plain["mesure"], "Nombre")
        self.assertEqual(plain["valeur_mesure_realisation"], 6.0)
        self.assertNotIn("types", plain)


class OracleExportPushTests(TestCase):
    """push_period_to_oracle() drives STAGING_IMPORT + PROCESS_STAGING correctly.

    Mocks the 'oracle' entry of django.db.connections directly (as seen by
    oracle_export.py), rather than Django's real Oracle backend - that
    backend's own connection/session-init plumbing was already validated by
    hand against the DATABASES config; these tests only cover our own SQL
    sequencing and error handling.
    """

    def setUp(self):
        self.rapport, self.ligne_breakdown, self.ligne_plain, self.participations = _make_catalog()
        self.mois = Mois.objects.create(numero=4, annee=2099)

    def _fake_connections(self, fetch_result):
        cursor = mock.MagicMock()
        cursor.__enter__.return_value = cursor
        cursor.__exit__.return_value = False
        cursor.fetchone.return_value = fetch_result

        conn = mock.MagicMock()
        conn.cursor.return_value = cursor
        return {"oracle": conn}, cursor, conn

    def test_push_success(self):
        connections, cursor, conn = self._fake_connections(("DONE", None))
        with mock.patch("spe_report.oracle_export.connections", connections):
            from spe_report.oracle_export import push_period_to_oracle

            ok, message = push_period_to_oracle(self.mois)

        self.assertTrue(ok)
        self.assertIn("Oracle", message)
        conn.close.assert_called_once()

    def test_push_reports_oracle_side_error(self):
        connections, cursor, conn = self._fake_connections(("ERROR", "ORA-01400: cannot insert NULL"))
        with mock.patch("spe_report.oracle_export.connections", connections):
            from spe_report.oracle_export import push_period_to_oracle

            ok, message = push_period_to_oracle(self.mois)

        self.assertFalse(ok)
        self.assertIn("ORA-01400", message)

    def test_push_sends_expected_statements(self):
        connections, cursor, conn = self._fake_connections(("DONE", None))
        with mock.patch("spe_report.oracle_export.connections", connections):
            from spe_report.oracle_export import push_period_to_oracle

            push_period_to_oracle(self.mois)

        statements = [call.args[0] for call in cursor.execute.call_args_list]
        self.assertTrue(any("INSERT INTO RAPPORT_SPE.STAGING_IMPORT" in s for s in statements))
        self.assertTrue(any("PROCESS_STAGING" in s for s in statements))
        self.assertTrue(any("SELECT STATUS, ERROR_MSG" in s for s in statements))
