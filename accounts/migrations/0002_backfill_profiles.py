from django.db import migrations


def backfill_profiles(apps, schema_editor):
    User = apps.get_model("auth", "User")
    Profile = apps.get_model("accounts", "Profile")
    for user in User.objects.all():
        Profile.objects.get_or_create(
            user=user,
            defaults={"role": "admin" if user.is_superuser else "moderator"},
        )


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(backfill_profiles, noop),
    ]
