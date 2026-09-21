from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.core.serializers.json import DjangoJSONEncoder
from django.db import models
from django.db.models import Q, UniqueConstraint

MOIS_LIBELLES = [
    "Janvier", "Février", "Mars", "Avril", "Mai", "Juin",
    "Juillet", "Août", "Septembre", "Octobre", "Novembre", "Décembre",
]


# ---------------------------------------------------------------------------
# Dimensions / catalog
# ---------------------------------------------------------------------------

class Mois(models.Model):
    """A reporting month (e.g. December 2025)."""

    numero = models.PositiveSmallIntegerField()
    annee = models.PositiveSmallIntegerField()

    class Meta:
        ordering = ["annee", "numero"]
        constraints = [
            UniqueConstraint(fields=["numero", "annee"], name="uniq_mois_numero_annee"),
        ]

    @property
    def libelle(self):
        return f"{MOIS_LIBELLES[self.numero - 1]} {self.annee}"

    def __str__(self):
        return self.libelle

    def mois_precedents_annee(self):
        """This month plus every earlier month of the same year, for cumul lookups."""
        return Mois.objects.filter(annee=self.annee, numero__lte=self.numero)

    def mois_n1(self):
        return Mois.objects.filter(annee=self.annee - 1, numero=self.numero).first()


class Rapport(models.Model):
    """One of the report sheets built on the LigneMesure/Mesure family."""

    code = models.SlugField(max_length=50, unique=True)
    libelle = models.CharField(max_length=255)
    ordre = models.PositiveSmallIntegerField(default=0)
    utilise_previsionnel = models.BooleanField(
        default=True,
        help_text="Whether this report tracks a Prévision column (some, like Export Val, only track Réalisation).",
    )

    class Meta:
        ordering = ["ordre", "libelle"]

    def __str__(self):
        return self.libelle


class MasterEntite(models.Model):
    """A section within a report sheet (e.g. 'Forage d'exploration' under Forages)."""

    rapport = models.ForeignKey(Rapport, on_delete=models.CASCADE, related_name="master_entites")
    libelle = models.CharField(max_length=255)
    ordre = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["rapport", "ordre", "libelle"]
        constraints = [
            UniqueConstraint(fields=["rapport", "libelle"], name="uniq_master_entite_rapport_libelle"),
        ]

    def __str__(self):
        return f"{self.rapport.libelle} / {self.libelle}"


class UniteMesure(models.Model):
    libelle = models.CharField(max_length=250, unique=True)

    class Meta:
        ordering = ["libelle"]

    def __str__(self):
        return self.libelle


class TypeParticipation(models.Model):
    libelle = models.CharField(max_length=50, unique=True)

    class Meta:
        ordering = ["libelle"]

    def __str__(self):
        return self.libelle


class LigneMesure(models.Model):
    """A single reportable line item, e.g. 'Pétrole Brut'."""

    master_entite = models.ForeignKey(MasterEntite, on_delete=models.CASCADE, related_name="lignes_mesure")
    libelle = models.CharField(max_length=250)
    unite_mesure = models.ForeignKey(
        UniteMesure, on_delete=models.SET_NULL, null=True, blank=True, related_name="lignes_mesure"
    )
    ordre = models.PositiveSmallIntegerField(default=0)
    types_participation = models.ManyToManyField(
        TypeParticipation,
        through="LigneMesureParticipation",
        related_name="lignes_mesure",
        blank=True,
    )

    class Meta:
        ordering = ["master_entite", "ordre", "libelle"]

    def __str__(self):
        return self.libelle


class LigneMesureParticipation(models.Model):
    """Which TypeParticipation breakdown rows apply to a given LigneMesure.

    An empty set for a line means it is entered as a single value with no
    breakdown. A non-empty set means the line is entered as one row per
    TypeParticipation here, and the aggregate (type_participation=None on
    Mesure) is an auto-computed sum of those rows.
    """

    ligne_mesure = models.ForeignKey(LigneMesure, on_delete=models.CASCADE, related_name="participations")
    type_participation = models.ForeignKey(
        TypeParticipation, on_delete=models.CASCADE, related_name="ligne_associations"
    )
    ordre = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["ligne_mesure", "ordre"]
        constraints = [
            UniqueConstraint(
                fields=["ligne_mesure", "type_participation"],
                name="uniq_ligne_mesure_type_participation",
            ),
        ]

    def __str__(self):
        return f"{self.ligne_mesure} / {self.type_participation}"


class MasterCategorie(models.Model):
    libelle = models.CharField(max_length=250, unique=True)
    ordre = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["ordre", "libelle"]

    def __str__(self):
        return self.libelle


class Categorie(models.Model):
    master_categorie = models.ForeignKey(
        MasterCategorie, on_delete=models.SET_NULL, null=True, blank=True, related_name="categories"
    )
    libelle = models.CharField(max_length=250, unique=True)
    ordre = models.PositiveSmallIntegerField(default=0)
    dont_libelle = models.CharField(
        max_length=250,
        blank=True,
        help_text="Label of this category's 'dont ...' breakdown row, if it has one (e.g. 'dont Cadres Sup.').",
    )

    class Meta:
        ordering = ["ordre", "libelle"]

    def __str__(self):
        return self.libelle


class Structure(models.Model):
    libelle = models.CharField(max_length=250, unique=True)
    ordre = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["ordre", "libelle"]

    def __str__(self):
        return self.libelle


class Action(models.Model):
    structure = models.ForeignKey(
        Structure, on_delete=models.SET_NULL, null=True, blank=True, related_name="actions"
    )
    libelle = models.CharField(max_length=250)
    ordre = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["structure", "ordre", "libelle"]
        constraints = [
            UniqueConstraint(fields=["structure", "libelle"], name="uniq_action_structure_libelle"),
        ]

    def __str__(self):
        return self.libelle


# ---------------------------------------------------------------------------
# Facts
# ---------------------------------------------------------------------------

class Mesure(models.Model):
    ligne_mesure = models.ForeignKey(LigneMesure, on_delete=models.CASCADE, related_name="mesures")
    mois = models.ForeignKey(Mois, on_delete=models.CASCADE, related_name="mesures")
    type_participation = models.ForeignKey(
        TypeParticipation, on_delete=models.CASCADE, null=True, blank=True, related_name="mesures"
    )

    valeur_previsionnel = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    valeur_realisation = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    valeur_realisation_n1 = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    valeur_previsionnel_cumul = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    valeur_realisation_cumul = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    valeur_realisation_cumul_n1 = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["ligne_mesure", "mois"]
        constraints = [
            UniqueConstraint(
                fields=["ligne_mesure", "mois", "type_participation"],
                name="uniq_mesure_ligne_mois_participation",
            ),
            UniqueConstraint(
                fields=["ligne_mesure", "mois"],
                condition=Q(type_participation__isnull=True),
                name="uniq_mesure_ligne_mois_total",
            ),
        ]

    def __str__(self):
        suffix = f" ({self.type_participation})" if self.type_participation_id else ""
        return f"{self.ligne_mesure} {self.mois}{suffix}"


class Objectif(models.Model):
    ligne_mesure = models.ForeignKey(LigneMesure, on_delete=models.CASCADE, related_name="objectifs")
    annee = models.PositiveSmallIntegerField()
    valeur = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["annee", "ligne_mesure"]
        constraints = [
            UniqueConstraint(fields=["ligne_mesure", "annee"], name="uniq_objectif_ligne_annee"),
        ]

    def __str__(self):
        return f"{self.ligne_mesure} {self.annee}"


class Effectif(models.Model):
    categorie = models.ForeignKey(Categorie, on_delete=models.CASCADE, related_name="effectifs")
    mois = models.ForeignKey(Mois, on_delete=models.CASCADE, related_name="effectifs")
    valeur = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    valeur_n1 = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["mois", "categorie"]
        constraints = [
            UniqueConstraint(fields=["categorie", "mois"], name="uniq_effectif_categorie_mois"),
        ]

    def __str__(self):
        return f"{self.categorie} {self.mois}"


class DontEffectif(models.Model):
    """The 'dont ...' annotation rows (e.g. 'dont Cadres Sup.') attached to a Categorie."""

    categorie = models.ForeignKey(Categorie, on_delete=models.CASCADE, related_name="dont_effectifs")
    mois = models.ForeignKey(Mois, on_delete=models.CASCADE, related_name="dont_effectifs")
    valeur = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    valeur_n1 = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["mois", "categorie"]
        constraints = [
            UniqueConstraint(fields=["categorie", "mois"], name="uniq_dont_effectif_categorie_mois"),
        ]

    def __str__(self):
        return f"dont {self.categorie} {self.mois}"


class MontantInvestissement(models.Model):
    mois = models.ForeignKey(Mois, on_delete=models.CASCADE, related_name="montants_investissement")
    structure = models.ForeignKey(Structure, on_delete=models.CASCADE, related_name="montants_investissement")
    action = models.ForeignKey(
        Action, on_delete=models.CASCADE, null=True, blank=True, related_name="montants_investissement"
    )
    valeur_realisation = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    valeur_objectif_revise = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["mois", "structure", "action"]
        constraints = [
            UniqueConstraint(
                fields=["mois", "structure", "action"],
                name="uniq_investissement_mois_structure_action",
            ),
            UniqueConstraint(
                fields=["mois", "structure"],
                condition=Q(action__isnull=True),
                name="uniq_investissement_mois_structure_total",
            ),
        ]

    def __str__(self):
        suffix = f" / {self.action}" if self.action_id else ""
        return f"{self.structure}{suffix} {self.mois}"


# ---------------------------------------------------------------------------
# Versioning
# ---------------------------------------------------------------------------

class PeriodeRapport(models.Model):
    """Lifecycle status of a reporting month: draft while it's being filled in,
    submitted (locked) once someone signs off on it."""

    STATUT_BROUILLON = "brouillon"
    STATUT_SOUMIS = "soumis"
    STATUT_CHOICES = [
        (STATUT_BROUILLON, "Brouillon"),
        (STATUT_SOUMIS, "Soumis"),
    ]

    mois = models.OneToOneField(Mois, on_delete=models.CASCADE, related_name="periode")
    statut = models.CharField(max_length=20, choices=STATUT_CHOICES, default=STATUT_BROUILLON)
    soumis_par = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    soumis_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-mois__annee", "-mois__numero"]
        permissions = [
            ("reopen_periode", "Can reopen a submitted period"),
        ]

    @property
    def est_verrouillee(self):
        return self.statut == self.STATUT_SOUMIS

    def __str__(self):
        return f"{self.mois} ({self.get_statut_display()})"


class ChangeLog(models.Model):
    """Generic audit trail entry for any fact row (Mesure, Effectif, ...)."""

    ACTION_CREATE = "create"
    ACTION_UPDATE = "update"
    ACTION_CHOICES = [
        (ACTION_CREATE, "Création"),
        (ACTION_UPDATE, "Modification"),
    ]

    content_type = models.ForeignKey("contenttypes.ContentType", on_delete=models.CASCADE)
    object_id = models.PositiveBigIntegerField()
    content_object = GenericForeignKey("content_type", "object_id")

    action = models.CharField(max_length=10, choices=ACTION_CHOICES)
    snapshot = models.JSONField(default=dict, blank=True, encoder=DjangoJSONEncoder)

    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    changed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-changed_at"]
        indexes = [
            models.Index(fields=["content_type", "object_id"]),
        ]

    def __str__(self):
        return f"{self.get_action_display()} {self.content_type} #{self.object_id}"
