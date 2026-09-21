from django.conf import settings
from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver


class Profile(models.Model):
    ROLE_ADMIN = "admin"
    ROLE_MODERATOR = "moderator"
    ROLE_CHOICES = [
        (ROLE_ADMIN, "Administrateur"),
        (ROLE_MODERATOR, "Modérateur"),
    ]

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile")
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default=ROLE_MODERATOR)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def is_admin(self):
        return self.role == self.ROLE_ADMIN

    def __str__(self):
        return f"{self.user.username} ({self.get_role_display()})"


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def create_profile_for_new_user(sender, instance, created, **kwargs):
    if not created:
        return
    Profile.objects.get_or_create(
        user=instance,
        defaults={"role": Profile.ROLE_ADMIN if instance.is_superuser else Profile.ROLE_MODERATOR},
    )
