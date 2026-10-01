"""Renvoie à CDD, pour chaque EADL, ses localités telles qu'elles sont stockées dans l'`Adl` (niveau
principal, niveaux choisis et villages, stabilisation et additionnels) : remplit les champs CDD qui
conservent le choix de l'agent (`main_administrative_id`, `*_administrative_choices`) sans rien
recalculer — les villages envoyés sont exactement ceux déjà connus de CDD. Pour un compte qui n'est pas
un facilitateur dans CDD mais un utilisateur du dashboard de même email (superviseurs, personnel), CDD
enregistre ces localités comme ses localités d'intervention.

Sans `--apply` : affiche seulement ce qui serait envoyé. Aucun email n'est envoyé aux facilitateurs,
sauf avec `--notify`.

    python manage.py push_adls_to_cdd                    # aperçu
    python manage.py push_adls_to_cdd --apply            # envoi
    python manage.py push_adls_to_cdd --apply --email x@y.z
"""
from collections import Counter

from django.conf import settings
from django.core.management.base import BaseCommand

from authentication.functions import update_user_adl_on_cdd_app
from authentication.models import GovernmentWorker
from issue.models import Adl


def _village_ids(ids):
    return [int(_id) for _id in (ids or []) if str(_id).isdigit()]


class Command(BaseCommand):
    help = "Renvoie à CDD les localités de chaque EADL (niveau principal, niveaux choisis, villages)."

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true', help="Envoyer réellement à CDD.")
        parser.add_argument('--email', action='append', help="Limiter à cet email (répétable).")
        parser.add_argument('--notify', action='store_true', help="Laisser CDD envoyer l'email de notification.")

    def handle(self, *args, **options):
        adls = Adl.objects.filter(is_deleted=False, representative__isnull=False).select_related('representative')
        if options['email']:
            adls = adls.filter(representative__email__in=options['email'])
        administrative_id_by_user = dict(GovernmentWorker.objects.values_list('user_id', 'administrative_id'))

        results = Counter()
        for adl in adls.order_by('representative__email'):
            email = adl.representative.email
            payload = dict(
                administrative_id=administrative_id_by_user.get(adl.representative_id),
                administrative_ids=adl.administrative_region_ids_value or [],
                additional_administrative_region_ids=adl.additional_administrative_region_ids_value or [],
            )
            villages = _village_ids(adl.smallest_administrative_level_ids_value)
            additional_villages = _village_ids(adl.additional_smallest_administrative_level_ids_value)
            if not options['apply']:
                self.stdout.write(
                    f"{email} | principal={payload['administrative_id']} | choix={len(payload['administrative_ids'])} "
                    f"| villages={len(villages)} | additionnels={len(additional_villages)}"
                )
                results['aperçu'] += 1
                continue
            try:
                response = update_user_adl_on_cdd_app(
                    email, settings.GRM_SECRET_KEY_GENRATE, villages, additional_villages,
                    notify=options['notify'], **payload,
                )
                if response.status_code == 200:
                    try:
                        kind = "utilisateur" if response.json().get('type') == 'user' else "facilitateur"
                    except ValueError:
                        kind = "facilitateur"
                    results[f"envoyé ({kind})"] += 1
                else:
                    # CDD répond 404 pour toute erreur : distinguer « ni facilitateur ni utilisateur » des vraies erreurs
                    try:
                        error = str(response.json().get('error', ''))
                    except ValueError:
                        error = response.text[:200]
                    if "Incorrect identifiers" in error or "Identifiants incorrects" in error:
                        results["pas de compte CDD (normal)"] += 1
                    else:
                        results["erreur CDD"] += 1
                        self.stderr.write(f"{email}: HTTP {response.status_code} {error[:300]}")
            except Exception as exc:
                results[f"erreur {type(exc).__name__}"] += 1
                self.stderr.write(f"{email}: {exc}")

        self.stdout.write(self.style.SUCCESS(f"{adls.count()} EADL — " + ", ".join(f"{k}: {v}" for k, v in results.items())))
