"""Push a submitted period into the corporate Oracle warehouse.

RAPPORT_SPE.MOIS is not written to directly: the real intake point is
RAPPORT_SPE.STAGING_IMPORT (a JSON payload per import) plus the
RAPPORT_SPE.PROCESS_STAGING procedure, which parses that JSON and populates
MOIS/RAPPORT/MASTER_ENTIRE/UNITE_MESURE/LIGNE_MESURE/TYPE_PARTICIPATION/MESURE.
This module builds a payload matching exactly what PROCESS_STAGING expects
(see its JSON_TABLE paths) and drives it through that same procedure, rather
than re-implementing its matching logic in Python.

PROCESS_STAGING only ingests the Mesure-based sheets (Rapport/MasterEntite/
LigneMesure/Mesure) - Effectifs, Investissements and Objectifs aren't covered.

Known limitations inherited from the Oracle-side schema/procedure (not
something this module works around):
- LIGNE_MESURE.ID_UNITE_MESURE and MESURE.VALEUR_MESURE_PREVISIONNEL are
  NOT NULL on the Oracle side. A LigneMesure with no unite_mesure, or a
  Mesure with no valeur_previsionnel, will make PROCESS_STAGING fail that
  whole staging row (STATUS='ERROR') - the exact error comes back in
  STAGING_IMPORT.ERROR_MSG and is surfaced by push_period_to_oracle().
"""
import json

from django.db import connections

from .models import Mesure, Rapport

MESURE_FIELDS = [
    "valeur_previsionnel",
    "valeur_realisation",
    "valeur_realisation_n1",
    "valeur_previsionnel_cumul",
    "valeur_realisation_cumul",
    "valeur_realisation_cumul_n1",
]

# Oracle-side JSON keys read by PROCESS_STAGING, in the same order as
# MESURE_FIELDS above.
ORACLE_MESURE_KEYS = [
    "valeur_mesure_previsionnel",
    "valeur_mesure_realisation",
    "valeur_mesure_realisation_n_passee",
    "valeur_mesure_previsionnel_cumul",
    "valeur_mesure_realisation_cumul",
    "valeur_mesure_realisation_cumul_n_passee",
]


def _num(value):
    return float(value) if value is not None else None


def _mesure_values(mesure):
    if mesure is None:
        return {key: None for key in ORACLE_MESURE_KEYS}
    return {
        oracle_key: _num(getattr(mesure, field))
        for oracle_key, field in zip(ORACLE_MESURE_KEYS, MESURE_FIELDS)
    }


def build_staging_payload(mois):
    """Build the JSON payload for one period, in the shape PROCESS_STAGING parses.

    Top-level shape:
        {"periode": {"mois": "<libelle>", "annee": <int>},
         "sheet_<code>": {"titre": "<Rapport.libelle>", "data": [
             {"title": "<MasterEntite.libelle>", "produits": [
                 {"title": "<LigneMesure.libelle>", "mesure": "<UniteMesure.libelle>",
                  "valeur_mesure_previsionnel": ..., ..., "types": [
                      {"title": "<TypeParticipation.libelle>", "valeur_mesure_previsionnel": ..., ...}
                  ]}
             ]}
         ]}, ...}
    """
    payload = {"periode": {"mois": mois.libelle, "annee": mois.annee}}

    mesures = {
        (m.ligne_mesure_id, m.type_participation_id): m
        for m in Mesure.objects.filter(mois=mois)
    }

    rapports = Rapport.objects.prefetch_related(
        "master_entites__lignes_mesure__unite_mesure",
        "master_entites__lignes_mesure__types_participation",
    )
    for rapport in rapports:
        data = []
        for master_entite in rapport.master_entites.all():
            produits = []
            for ligne in master_entite.lignes_mesure.all():
                total = mesures.get((ligne.id, None))
                produit = {
                    "title": ligne.libelle,
                    "mesure": ligne.unite_mesure.libelle if ligne.unite_mesure_id else None,
                    **_mesure_values(total),
                }
                types = []
                for type_participation in ligne.types_participation.all():
                    type_mesure = mesures.get((ligne.id, type_participation.id))
                    types.append({
                        "title": type_participation.libelle,
                        **_mesure_values(type_mesure),
                    })
                if types:
                    produit["types"] = types
                produits.append(produit)
            if produits:
                data.append({"title": master_entite.libelle, "produits": produits})
        payload[f"sheet_{rapport.code}"] = {"titre": rapport.libelle, "data": data}

    return payload


def push_period_to_oracle(mois):
    """Insert this period's payload into STAGING_IMPORT and run PROCESS_STAGING.

    Returns (ok: bool, message: str). Never raises for Oracle-side failures
    (network errors, ORA errors) - those come back as (False, <detail>) so a
    failed push doesn't block the local submission that triggered it.
    """
    payload_json = json.dumps(build_staging_payload(mois), ensure_ascii=False)
    wb_name = f"{mois.libelle} (HCNDash export)"

    conn = connections["oracle"]
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "INSERT INTO RAPPORT_SPE.STAGING_IMPORT (WB_NAME, STATUS, PAYLOAD) "
                "VALUES (%s, 'PENDING', %s)",
                [wb_name, payload_json],
            )
            conn.commit()

            cursor.execute("BEGIN RAPPORT_SPE.PROCESS_STAGING; END;")
            conn.commit()

            cursor.execute(
                "SELECT STATUS, ERROR_MSG FROM RAPPORT_SPE.STAGING_IMPORT "
                "WHERE WB_NAME = %s ORDER BY ID DESC FETCH FIRST 1 ROW ONLY",
                [wb_name],
            )
            row = cursor.fetchone()
    except Exception as exc:
        return False, f"Connexion Oracle impossible : {exc}"
    finally:
        conn.close()

    if row is None:
        return False, "Aucune trace de l'import cote Oracle apres traitement."

    status, error_msg = row
    if status == "DONE":
        return True, "Periode exportee avec succes vers Oracle (RAPPORT_SPE)."

    error_text = error_msg.read() if hasattr(error_msg, "read") else error_msg
    return False, f"Echec de l'import Oracle (statut={status}) : {error_text}"
