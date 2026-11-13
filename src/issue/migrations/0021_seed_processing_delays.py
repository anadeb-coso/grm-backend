"""Délais de traitement par défaut (modifiables ensuite depuis /diagnostics/processing-delays/) :
Village (CVGP) 10 jours ouvrables, Canton (CCaGP) 20 jours ouvrables, Commune (CCoGP) 20 jours
ouvrables, National (CNGP) 45 jours (maximum de « 30 à 45 jours »). Préfecture et Région : pas de
délai tant qu'il n'est pas saisi."""
from django.db import migrations

DEFAULTS = [
    ('Village', 'Comité Villageois de Gestion des Plaintes (CVGP)', 10, True),
    ('Canton', 'Comité Cantonal de Gestion des Plaintes (CCaGP)', 20, True),
    ('Commune', 'Comité Communal de Gestion des Plaintes (CCoGP)', 20, True),
    ('Prefecture', '', None, True),
    ('Region', '', None, True),
    ('Country', 'Comité National de Gestion des Plaintes (CNGP)', 45, False),
]


def seed(apps, schema_editor):
    ProcessingDelay = apps.get_model('issue', 'ProcessingDelay')
    for level, committee, days, working in DEFAULTS:
        ProcessingDelay.objects.get_or_create(
            level=level, defaults={'committee_name': committee, 'delay_days': days, 'working_days': working},
        )


class Migration(migrations.Migration):

    dependencies = [
        ('issue', '0020_processing_delays_received_escalation_dates'),
    ]

    operations = [
        migrations.RunPython(seed, migrations.RunPython.noop),
    ]
