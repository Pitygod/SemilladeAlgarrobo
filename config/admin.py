from django.conf import settings
from django.contrib import admin

admin.site.site_header = f'{settings.SITE_NAME} - Administración'
admin.site.site_title = settings.SITE_NAME
admin.site.index_title = 'Panel de administración'
