from django.contrib.contenttypes.models import ContentType
from django.forms.models import model_to_dict

from .models import ChangeLog

# Fields every fact model carries that aren't meaningful to diff/snapshot.
_IGNORED_FIELDS = {"id", "created_by", "created_at", "updated_at"}


def _snapshot(instance):
    data = model_to_dict(instance)
    return {k: v for k, v in data.items() if k not in _IGNORED_FIELDS}


def record_change(instance, action, user, previous_snapshot=None):
    """Write a ChangeLog entry for a fact instance if anything actually changed.

    `previous_snapshot` is the dict returned by a prior call to
    `snapshot_before(instance)`, taken before the instance was mutated/saved.
    For `action="create"` there is no previous state to compare against.
    """
    new_snapshot = _snapshot(instance)
    if action == ChangeLog.ACTION_UPDATE and previous_snapshot == new_snapshot:
        return None

    payload = {"after": new_snapshot}
    if previous_snapshot is not None:
        payload["before"] = previous_snapshot

    return ChangeLog.objects.create(
        content_type=ContentType.objects.get_for_model(instance),
        object_id=instance.pk,
        action=action,
        snapshot=payload,
        changed_by=user if getattr(user, "is_authenticated", False) else None,
    )


def snapshot_before(instance):
    """Capture the current DB state of a fact row before mutating it in memory."""
    return _snapshot(instance)
