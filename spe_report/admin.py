from django.contrib import admin

from .models import (
    Action,
    Categorie,
    ChangeLog,
    DontEffectif,
    Effectif,
    LigneMesure,
    LigneMesureParticipation,
    MasterCategorie,
    MasterEntite,
    Mesure,
    Mois,
    MontantInvestissement,
    Objectif,
    PeriodeRapport,
    Rapport,
    Structure,
    TypeParticipation,
    UniteMesure,
)


@admin.register(Mois)
class MoisAdmin(admin.ModelAdmin):
    list_display = ("libelle", "numero", "annee")
    list_filter = ("annee",)
    ordering = ("-annee", "-numero")


@admin.register(Rapport)
class RapportAdmin(admin.ModelAdmin):
    list_display = ("libelle", "code", "ordre", "utilise_previsionnel")
    ordering = ("ordre",)


@admin.register(MasterEntite)
class MasterEntiteAdmin(admin.ModelAdmin):
    list_display = ("libelle", "rapport", "ordre")
    list_filter = ("rapport",)


@admin.register(UniteMesure)
class UniteMesureAdmin(admin.ModelAdmin):
    list_display = ("libelle",)
    search_fields = ("libelle",)


@admin.register(TypeParticipation)
class TypeParticipationAdmin(admin.ModelAdmin):
    list_display = ("libelle",)


class LigneMesureParticipationInline(admin.TabularInline):
    model = LigneMesureParticipation
    extra = 1


@admin.register(LigneMesure)
class LigneMesureAdmin(admin.ModelAdmin):
    list_display = ("libelle", "master_entite", "unite_mesure", "ordre")
    list_filter = ("master_entite__rapport", "master_entite")
    search_fields = ("libelle",)
    inlines = [LigneMesureParticipationInline]


@admin.register(MasterCategorie)
class MasterCategorieAdmin(admin.ModelAdmin):
    list_display = ("libelle", "ordre")


@admin.register(Categorie)
class CategorieAdmin(admin.ModelAdmin):
    list_display = ("libelle", "master_categorie", "dont_libelle", "ordre")
    list_filter = ("master_categorie",)


@admin.register(Structure)
class StructureAdmin(admin.ModelAdmin):
    list_display = ("libelle", "ordre")


@admin.register(Action)
class ActionAdmin(admin.ModelAdmin):
    list_display = ("libelle", "structure", "ordre")
    list_filter = ("structure",)


@admin.register(Mesure)
class MesureAdmin(admin.ModelAdmin):
    list_display = (
        "ligne_mesure", "mois", "type_participation",
        "valeur_previsionnel", "valeur_realisation",
    )
    list_filter = ("mois", "ligne_mesure__master_entite__rapport")
    readonly_fields = ("created_at", "updated_at")


@admin.register(Objectif)
class ObjectifAdmin(admin.ModelAdmin):
    list_display = ("ligne_mesure", "annee", "valeur")
    list_filter = ("annee",)
    readonly_fields = ("created_at", "updated_at")


@admin.register(Effectif)
class EffectifAdmin(admin.ModelAdmin):
    list_display = ("categorie", "mois", "valeur", "valeur_n1")
    list_filter = ("mois",)
    readonly_fields = ("created_at", "updated_at")


@admin.register(DontEffectif)
class DontEffectifAdmin(admin.ModelAdmin):
    list_display = ("categorie", "mois", "valeur", "valeur_n1")
    list_filter = ("mois",)
    readonly_fields = ("created_at", "updated_at")


@admin.register(MontantInvestissement)
class MontantInvestissementAdmin(admin.ModelAdmin):
    list_display = ("structure", "action", "mois", "valeur_realisation", "valeur_objectif_revise")
    list_filter = ("mois", "structure")
    readonly_fields = ("created_at", "updated_at")


@admin.register(PeriodeRapport)
class PeriodeRapportAdmin(admin.ModelAdmin):
    list_display = ("mois", "statut", "soumis_par", "soumis_at")
    list_filter = ("statut",)
    readonly_fields = ("created_at", "updated_at")


@admin.register(ChangeLog)
class ChangeLogAdmin(admin.ModelAdmin):
    list_display = ("changed_at", "action", "content_type", "object_id", "changed_by")
    list_filter = ("action", "content_type")
    readonly_fields = ("content_type", "object_id", "action", "snapshot", "changed_by", "changed_at")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
