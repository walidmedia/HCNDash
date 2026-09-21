from django.contrib import messages
from django.contrib.auth import get_user_model
from django.shortcuts import get_object_or_404, redirect, render

from .decorators import admin_required
from .forms import UserCreateForm, UserRoleForm

User = get_user_model()


@admin_required
def user_list(request):
    users = User.objects.select_related("profile").order_by("username")
    return render(request, "accounts/user_list.html", {"users": users})


@admin_required
def user_create(request):
    if request.method == "POST":
        form = UserCreateForm(request.POST)
        if form.is_valid():
            user = User.objects.create_user(
                username=form.cleaned_data["username"],
                email=form.cleaned_data["email"],
                password=form.cleaned_data["password"],
            )
            user.profile.role = form.cleaned_data["role"]
            user.profile.save(update_fields=["role"])
            messages.success(request, f"Utilisateur « {user.username} » créé.")
            return redirect("accounts:user_list")
    else:
        form = UserCreateForm()
    return render(request, "accounts/user_form.html", {"form": form, "title": "Nouvel utilisateur"})


@admin_required
def user_edit(request, pk):
    target = get_object_or_404(User, pk=pk)
    if request.method == "POST":
        form = UserRoleForm(request.POST)
        if form.is_valid():
            target.profile.role = form.cleaned_data["role"]
            target.profile.save(update_fields=["role"])
            target.is_active = form.cleaned_data["is_active"]
            target.save(update_fields=["is_active"])
            messages.success(request, f"Utilisateur « {target.username} » mis à jour.")
            return redirect("accounts:user_list")
    else:
        form = UserRoleForm(initial={"role": target.profile.role, "is_active": target.is_active})
    return render(
        request,
        "accounts/user_form.html",
        {"form": form, "title": f"Modifier {target.username}", "target": target},
    )
