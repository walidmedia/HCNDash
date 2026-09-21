from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .models import Dataset, Periode, Row


class ArchivePeriodTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user("alice", password="pw")
        self.superuser = User.objects.create_superuser("admin", "admin@example.com", "pw")
        self.periode = Periode.objects.create(numero=1, annee=2098)
        self.dataset = Dataset.objects.create(
            name="Ventes", columns=["a", "b"], periode=self.periode, created_by=self.user
        )
        Row.objects.create(dataset=self.dataset, data={"a": "1", "b": "2"})
        self.client.login(username="alice", password="pw")

    def test_period_list_and_create(self):
        resp = self.client.get(reverse("archive:period_list"))
        self.assertEqual(resp.status_code, 200)

        resp = self.client.post(reverse("archive:period_list"), {"numero": 2, "annee": 2098})
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(Periode.objects.filter(numero=2, annee=2098).exists())

    def test_locked_period_rejects_row_edits(self):
        self.client.post(reverse("archive:period_submit", args=[self.periode.id]))
        self.periode.refresh_from_db()
        self.assertTrue(self.periode.est_verrouillee)

        row = self.dataset.rows.first()
        resp = self.client.post(
            reverse("archive:row_edit", args=[self.dataset.pk, row.pk]), {"a": "999", "b": "2"}
        )
        self.assertEqual(resp.status_code, 302)
        row.refresh_from_db()
        self.assertEqual(row.data["a"], "1")  # unchanged, edit was rejected

    def test_moderator_cannot_delete_or_reopen(self):
        resp = self.client.post(reverse("archive:dataset_delete", args=[self.dataset.pk]))
        self.assertEqual(resp.status_code, 403)
        self.assertTrue(Dataset.objects.filter(pk=self.dataset.pk).exists())

        self.client.post(reverse("archive:period_submit", args=[self.periode.id]))
        resp = self.client.post(reverse("archive:period_reopen", args=[self.periode.id]))
        self.assertEqual(resp.status_code, 403)

    def test_admin_can_delete_and_reopen(self):
        self.client.logout()
        self.client.login(username="admin", password="pw")

        self.client.post(reverse("archive:period_submit", args=[self.periode.id]))
        resp = self.client.post(reverse("archive:period_reopen", args=[self.periode.id]))
        self.assertEqual(resp.status_code, 302)
        self.periode.refresh_from_db()
        self.assertFalse(self.periode.est_verrouillee)

        resp = self.client.post(reverse("archive:dataset_delete", args=[self.dataset.pk]))
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(Dataset.objects.filter(pk=self.dataset.pk).exists())

    def test_autosave_add_row_returns_json(self):
        resp = self.client.post(
            reverse("archive:row_add", args=[self.dataset.pk]),
            {"a": "5", "b": "6"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "ok")
        self.assertTrue(Row.objects.filter(data__a="5").exists())

    def test_export_xlsx_and_csv(self):
        resp = self.client.get(reverse("archive:dataset_export", args=[self.dataset.pk, "xlsx"]))
        self.assertEqual(resp.status_code, 200)
        self.assertIn("spreadsheetml", resp["Content-Type"])

        resp = self.client.get(reverse("archive:dataset_export", args=[self.dataset.pk, "csv"]))
        self.assertEqual(resp.status_code, 200)
        self.assertIn("text/csv", resp["Content-Type"])

        resp = self.client.get(reverse("archive:period_export", args=[self.periode.id, "xlsx"]))
        self.assertEqual(resp.status_code, 200)
