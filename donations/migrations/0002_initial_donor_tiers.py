"""Crea los 4 niveles de donador iniciales.

Los importes y textos son editables desde Administración > Niveles de donador.
Las descripciones son deliberadamente generales: no prometen beneficios que la
organización no haya definido.
"""
from decimal import Decimal

from django.db import migrations

TIERS = [
    {
        'slug': 'donador-inicial', 'name': 'Donador Inicial', 'amount': Decimal('5000'), 'order': 1,
        'description': 'Un primer paso para acompañar de forma constante a las comunidades.',
        'purpose': 'Tu aporte mensual suma a las acciones de asistencia que realiza la organización.',
    },
    {
        'slug': 'donador-solidario', 'name': 'Donador Solidario', 'amount': Decimal('10000'), 'order': 2,
        'description': 'Un compromiso mensual que ayuda a sostener el trabajo comunitario en el tiempo.',
        'purpose': 'Contribuye a dar continuidad a la ayuda que llega a las comunidades.',
        'is_highlighted': True,
    },
    {
        'slug': 'donador-colaborador', 'name': 'Donador Colaborador', 'amount': Decimal('20000'), 'order': 3,
        'description': 'Un aporte mensual que fortalece la capacidad de respuesta ante las necesidades activas.',
        'purpose': 'Acompaña la atención de las necesidades que publican las comunidades.',
    },
    {
        'slug': 'donador-padrino', 'name': 'Donador Padrino', 'amount': Decimal('50000'), 'order': 4,
        'description': 'El mayor nivel de compromiso para acompañar a las comunidades de manera sostenida.',
        'purpose': 'Brinda previsibilidad al trabajo de la organización con las comunidades.',
    },
]


def forwards(apps, schema_editor):
    DonorTier = apps.get_model('donations', 'DonorTier')
    for data in TIERS:
        DonorTier.objects.get_or_create(slug=data['slug'], defaults=data)


def backwards(apps, schema_editor):
    DonorTier = apps.get_model('donations', 'DonorTier')
    DonorTier.objects.filter(slug__in=[t['slug'] for t in TIERS], subscriptions__isnull=True).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('donations', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
