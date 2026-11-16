from django.conf import settings


def site(request):
    """Datos globales del sitio disponibles en todos los templates."""
    return {
        'SITE_NAME': settings.SITE_NAME,
        'SOCIAL_LINKS': settings.SOCIAL_LINKS,
    }
