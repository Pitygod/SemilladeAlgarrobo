"""Pasa la imagen única existente de cada comunidad a la nueva galería.

No copia ni mueve archivos: la foto de la galería apunta al MISMO archivo que
``Community.image``, así no se rompe ninguna imagen existente. El campo anterior
se conserva por compatibilidad.
"""
from django.db import migrations


def forwards(apps, schema_editor):
    Community = apps.get_model('communities', 'Community')
    CommunityImage = apps.get_model('communities', 'CommunityImage')
    for community in Community.objects.exclude(image='').exclude(image__isnull=True):
        if not CommunityImage.objects.filter(community=community, image=community.image.name).exists():
            CommunityImage.objects.create(
                community=community,
                image=community.image.name,
                caption='',
                order=0,
                is_main=not CommunityImage.objects.filter(community=community, is_main=True).exists(),
            )


def backwards(apps, schema_editor):
    # Solo elimina los registros migrados (el archivo sigue referenciado por Community.image).
    Community = apps.get_model('communities', 'Community')
    CommunityImage = apps.get_model('communities', 'CommunityImage')
    for community in Community.objects.exclude(image='').exclude(image__isnull=True):
        CommunityImage.objects.filter(community=community, image=community.image.name).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('communities', '0003_community_is_featured_community_location_and_more'),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
