from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm

from .models import Profile

User = get_user_model()


class LoginForm(AuthenticationForm):
    username = forms.CharField(
        widget=forms.TextInput(attrs={"class": "form-control", "autofocus": True})
    )
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={"class": "form-control"})
    )


class UserCreateForm(forms.Form):
    username = forms.CharField(
        max_length=150, label="Identifiant", widget=forms.TextInput(attrs={"class": "form-control"})
    )
    email = forms.EmailField(
        required=False, label="Email", widget=forms.EmailInput(attrs={"class": "form-control"})
    )
    password = forms.CharField(
        label="Mot de passe", widget=forms.PasswordInput(attrs={"class": "form-control"})
    )
    role = forms.ChoiceField(
        choices=Profile.ROLE_CHOICES, label="Rôle", widget=forms.Select(attrs={"class": "form-select"})
    )

    def clean_username(self):
        username = self.cleaned_data["username"]
        if User.objects.filter(username=username).exists():
            raise forms.ValidationError("Ce nom d'utilisateur existe déjà.")
        return username


class UserRoleForm(forms.Form):
    role = forms.ChoiceField(
        choices=Profile.ROLE_CHOICES, label="Rôle", widget=forms.Select(attrs={"class": "form-select"})
    )
    is_active = forms.BooleanField(
        required=False, label="Compte actif", widget=forms.CheckboxInput(attrs={"class": "form-check-input"})
    )
