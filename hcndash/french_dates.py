MOIS_LIBELLES = [
    "Janvier", "Février", "Mars", "Avril", "Mai", "Juin",
    "Juillet", "Août", "Septembre", "Octobre", "Novembre", "Décembre",
]


def mois_libelle(numero, annee):
    return f"{MOIS_LIBELLES[numero - 1]} {annee}"
