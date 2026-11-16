from django.contrib import admin, messages

from . import services
from .gateway import MercadoPagoError
from .models import DonorTier, OneTimeDonation, Subscription, SubscriptionPayment, WebhookEvent


@admin.register(DonorTier)
class DonorTierAdmin(admin.ModelAdmin):
    list_display = ('name', 'amount', 'frequency_months', 'order', 'is_highlighted', 'is_active')
    list_editable = ('amount', 'order', 'is_highlighted', 'is_active')
    prepopulated_fields = {'slug': ('name',)}


MP_DONATION_FIELDS = ('mp_order_id', 'mp_status', 'mp_status_detail', 'mp_payment_id', 'payment_method',
                      'payment_type', 'checkout_url', 'error_message', 'need_donation', 'approved_at',
                      'last_synced_at', 'created_at', 'updated_at')


@admin.register(OneTimeDonation)
class OneTimeDonationAdmin(admin.ModelAdmin):
    list_display = ('short_reference', 'created_at', 'user', 'amount', 'status', 'community', 'need',
                    'mp_order_id', 'payment_method')
    list_filter = ('status', 'payment_type', 'created_at')
    search_fields = ('reference', 'mp_order_id', 'mp_payment_id', 'user__username', 'user__email')
    # El estado y los importes solo cambian vía Mercado Pago, nunca a mano.
    readonly_fields = ('reference', 'user', 'community', 'need', 'amount', 'currency', 'status') + MP_DONATION_FIELDS
    actions = ['sync_with_mercadopago']
    date_hierarchy = 'created_at'

    def has_add_permission(self, request):
        return False

    @admin.action(description='Verificar estado en Mercado Pago')
    def sync_with_mercadopago(self, request, queryset):
        ok = 0
        for donation in queryset.exclude(mp_order_id=None):
            try:
                services.refresh_donation(donation)
                ok += 1
            except MercadoPagoError as exc:
                self.message_user(request, f'{donation}: {exc}', messages.ERROR)
        self.message_user(request, f'{ok} donaciones verificadas.')


class SubscriptionPaymentInline(admin.TabularInline):
    model = SubscriptionPayment
    extra = 0
    can_delete = False
    readonly_fields = ('mp_authorized_payment_id', 'mp_payment_id', 'amount', 'status', 'payment_status',
                       'payment_status_detail', 'debit_date')
    fields = readonly_fields

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = ('short_reference', 'created_at', 'user', 'tier_name', 'amount', 'status',
                    'next_payment_date', 'mp_preapproval_id')
    list_filter = ('status', 'tier')
    search_fields = ('reference', 'mp_preapproval_id', 'payer_email', 'user__username', 'user__email')
    readonly_fields = ('reference', 'user', 'tier', 'tier_name', 'amount', 'currency', 'frequency_months',
                       'payer_email', 'status', 'mp_preapproval_id', 'mp_status', 'init_point',
                       'next_payment_date', 'started_at', 'cancelled_at', 'error_message', 'created_at',
                       'updated_at', 'last_synced_at')
    inlines = [SubscriptionPaymentInline]
    actions = ['sync_with_mercadopago']

    def has_add_permission(self, request):
        return False

    @admin.action(description='Verificar estado en Mercado Pago')
    def sync_with_mercadopago(self, request, queryset):
        ok = 0
        for subscription in queryset.exclude(mp_preapproval_id=None):
            try:
                services.refresh_subscription(subscription)
                ok += 1
            except MercadoPagoError as exc:
                self.message_user(request, f'{subscription}: {exc}', messages.ERROR)
        self.message_user(request, f'{ok} suscripciones verificadas.')


@admin.register(WebhookEvent)
class WebhookEventAdmin(admin.ModelAdmin):
    list_display = ('received_at', 'topic', 'action', 'resource_id', 'result', 'attempts', 'live_mode')
    list_filter = ('topic', 'result', 'live_mode')
    search_fields = ('resource_id', 'request_id')
    readonly_fields = [f.name for f in WebhookEvent._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
