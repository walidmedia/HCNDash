from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied


def admin_required(view_func):
    """Like login_required, but also requires the admin role."""

    @login_required
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.profile.is_admin:
            raise PermissionDenied("Réservé aux administrateurs.")
        return view_func(request, *args, **kwargs)

    return wrapper
