from django.urls import path

from . import views

app_name = 'donations'

urlpatterns = [
    path('', views.donate_start, name='start'),
    path('unica/', views.one_time, name='one_time'),
    path('donacion/<uuid:reference>/', views.donation_detail, name='donation_detail'),
    path('mensual/', views.monthly, name='monthly'),
    path('mensual/<slug:slug>/', views.subscribe, name='subscribe'),
    path('suscripcion/<uuid:reference>/', views.subscription_detail, name='subscription_detail'),
    path('suscripcion/<uuid:reference>/cancelar/', views.subscription_cancel, name='subscription_cancel'),
    path('mi-actividad/', views.my_activity, name='my_activity'),
    path('webhooks/mercadopago/', views.mercadopago_webhook, name='webhook'),
]
