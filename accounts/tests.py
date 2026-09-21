from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .models import Profile


class ProfileRoleTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.moderator = User.objects.create_user("bob", password="pw")
        self.admin = User.objects.create_superuser("admin", "admin@example.com", "pw")

    def test_new_users_get_a_role_automatically(self):
        self.assertEqual(self.moderator.profile.role, Profile.ROLE_MODERATOR)
        self.assertTrue(self.admin.profile.is_admin)

    def test_user_management_requires_admin_role(self):
        self.client.login(username="bob", password="pw")
        resp = self.client.get(reverse("accounts:user_list"))
        self.assertEqual(resp.status_code, 403)

    def test_admin_can_create_user_with_role(self):
        self.client.login(username="admin", password="pw")
        resp = self.client.post(
            reverse("accounts:user_create"),
            {"username": "carol", "email": "", "password": "pw12345", "role": Profile.ROLE_MODERATOR},
        )
        self.assertEqual(resp.status_code, 302)
        User = get_user_model()
        carol = User.objects.get(username="carol")
        self.assertEqual(carol.profile.role, Profile.ROLE_MODERATOR)

    def test_admin_can_change_role(self):
        self.client.login(username="admin", password="pw")
        resp = self.client.post(
            reverse("accounts:user_edit", args=[self.moderator.pk]),
            {"role": Profile.ROLE_ADMIN, "is_active": "on"},
        )
        self.assertEqual(resp.status_code, 302)
        self.moderator.profile.refresh_from_db()
        self.assertTrue(self.moderator.profile.is_admin)
