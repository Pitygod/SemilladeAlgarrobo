"""Modelos de donaciones con Mercado Pago.

Relaciones:
    Usuario → OneTimeDonation (donación única) → Orden de Mercado Pago (mp_order_id)
    Usuario → Subscription (donador mensual) → SubscriptionPayment (cobros recurrentes)

No se guarda ningún dato de tarjeta: Mercado Pago gestiona los medios de pago.
"""
import uuid

from django.conf import settings
from django.db import models
from django.urls import reverse


class DonorTier(models.Model):
    """Nivel de donador mensual. Editable desde el panel de administración."""

    name = models.CharField('nombre', max_length=80)
    slug = models.SlugField('identificador', max_length=80, unique=True)
    amount = models.DecimalField('importe mensual (ARS)', max_digits=12, decimal_places=2)
    frequency_months = models.PositiveSmallIntegerField(
        'frecuencia (meses)', default=1,
        help_text='Cada cuántos meses se realiza el cobro. 1 = mensual.',
    )
    description = models.TextField('descripción')
    purpose = models.CharField(
        'finalidad simbólica', max_length=255, blank=True,
        help_text='Frase breve sobre a qué contribuye este aporte. No prometer beneficios no definidos.',
    )
    order = models.PositiveSmallIntegerField('orden', default=0)
    is_highlighted = models.BooleanField('destacado', default=False)
    is_active = models.BooleanField('activo', default=True)

    class Meta:
        verbose_name = 'nivel de donador'
        verbose_name_plural = 'niveles de donador'
        ordering = ['order', 'amount']

    def __str__(self):
        return f'{self.name} (${self.amount:,.0f})'

    @property
    def frequency_label(self):
        return 'mes' if self.frequency_months == 1 else f'{self.frequency_months} meses'


class OneTimeDonation(models.Model):
    """Donación única pagada con Checkout Pro (Orders API)."""

    class Status(models.TextChoices):
        PENDING = 'pendiente', 'Pendiente'
        IN_PROCESS = 'en_proceso', 'En proceso'
        APPROVED = 'aprobada', 'Aprobada'
        REJECTED = 'rechazada', 'Rechazada'
        CANCELLED = 'cancelada', 'Cancelada'
        EXPIRED = 'vencida', 'Vencida'
        REFUNDED = 'reembolsada', 'Reembolsada'
        PARTIALLY_REFUNDED = 'reembolso_parcial', 'Reembolsada parcialmente'
        ERROR = 'error', 'Error al iniciar el pago'

    FINAL_STATUSES = {Status.APPROVED, Status.REJECTED, Status.CANCELLED, Status.EXPIRED,
                      Status.REFUNDED, Status.ERROR}

    reference = models.UUIDField('referencia', default=uuid.uuid4, unique=True, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='online_donations', verbose_name='donador',
    )
    community = models.ForeignKey(
        'communities.Community', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='online_donations', verbose_name='comunidad',
    )
    need = models.ForeignKey(
        'communities.Need', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='online_donations', verbose_name='necesidad',
    )
    amount = models.DecimalField('importe', max_digits=12, decimal_places=2)
    currency = models.CharField('moneda', max_length=3, default='ARS')
    status = models.CharField('estado', max_length=20, choices=Status.choices, default=Status.PENDING,
                              db_index=True)

    # Datos de Mercado Pago (nunca datos de tarjeta).
    mp_order_id = models.CharField('ID de orden MP', max_length=64, unique=True, null=True, blank=True)
    mp_status = models.CharField('estado MP', max_length=40, blank=True)
    mp_status_detail = models.CharField('detalle de estado MP', max_length=60, blank=True)
    mp_payment_id = models.CharField('ID de pago MP', max_length=64, blank=True, db_index=True)
    payment_method = models.CharField('medio de pago', max_length=60, blank=True)
    payment_type = models.CharField('tipo de medio de pago', max_length=40, blank=True)
    checkout_url = models.URLField('URL de checkout', max_length=600, blank=True)
    error_message = models.CharField('error', max_length=255, blank=True)

    # Registro creado en communities.Donation cuando el pago se aprueba y la
    # donación está dirigida a una necesidad (actualiza el progreso recaudado).
    need_donation = models.OneToOneField(
        'communities.Donation', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='online_donation', verbose_name='registro en la necesidad',
    )

    created_at = models.DateTimeField('creada', auto_now_add=True)
    updated_at = models.DateTimeField('actualizada', auto_now=True)
    approved_at = models.DateTimeField('aprobada el', null=True, blank=True)
    last_synced_at = models.DateTimeField('última verificación con MP', null=True, blank=True)

    class Meta:
        verbose_name = 'donación única (Mercado Pago)'
        verbose_name_plural = 'donaciones únicas (Mercado Pago)'
        ordering = ['-created_at']

    def __str__(self):
        return f'Donación {self.short_reference} - ${self.amount:,.0f} ({self.get_status_display()})'

    @property
    def short_reference(self):
        return self.reference.hex[:10].upper()

    @property
    def is_final(self):
        return self.status in self.FINAL_STATUSES

    def get_absolute_url(self):
        return reverse('donations:donation_detail', args=[self.reference])


class Subscription(models.Model):
    """Donación recurrente (suscripción / preapproval de Mercado Pago)."""

    class Status(models.TextChoices):
        PENDING = 'pendiente', 'Pendiente de autorización'
        AUTHORIZED = 'activa', 'Activa'
        PAUSED = 'pausada', 'Pausada'
        CANCELLED = 'cancelada', 'Cancelada'
        REJECTED = 'rechazada', 'Rechazada'
        ERROR = 'error', 'Error al iniciar'

    CANCELLABLE_STATUSES = {Status.PENDING, Status.AUTHORIZED, Status.PAUSED}

    reference = models.UUIDField('referencia', default=uuid.uuid4, unique=True, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='donation_subscriptions', verbose_name='donador',
    )
    tier = models.ForeignKey(
        DonorTier, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='subscriptions', verbose_name='nivel',
    )
    # Copia de los datos del nivel al momento de suscribirse (el nivel puede cambiar luego).
    tier_name = models.CharField('nombre del nivel', max_length=80)
    amount = models.DecimalField('importe', max_digits=12, decimal_places=2)
    currency = models.CharField('moneda', max_length=3, default='ARS')
    frequency_months = models.PositiveSmallIntegerField('frecuencia (meses)', default=1)
    payer_email = models.EmailField('email de la cuenta de Mercado Pago')
    status = models.CharField('estado', max_length=20, choices=Status.choices, default=Status.PENDING,
                              db_index=True)

    mp_preapproval_id = models.CharField('ID de suscripción MP', max_length=64, unique=True, null=True, blank=True)
    mp_status = models.CharField('estado MP', max_length=40, blank=True)
    init_point = models.URLField('URL de autorización', max_length=600, blank=True)
    next_payment_date = models.DateTimeField('próximo cobro', null=True, blank=True)
    started_at = models.DateTimeField('inicio', null=True, blank=True)
    cancelled_at = models.DateTimeField('cancelada el', null=True, blank=True)
    error_message = models.CharField('error', max_length=255, blank=True)

    created_at = models.DateTimeField('creada', auto_now_add=True)
    updated_at = models.DateTimeField('actualizada', auto_now=True)
    last_synced_at = models.DateTimeField('última verificación con MP', null=True, blank=True)

    class Meta:
        verbose_name = 'suscripción de donador'
        verbose_name_plural = 'suscripciones de donadores'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.tier_name} - ${self.amount:,.0f}/mes ({self.get_status_display()})'

    @property
    def short_reference(self):
        return self.reference.hex[:10].upper()

    @property
    def can_be_cancelled(self):
        return self.status in self.CANCELLABLE_STATUSES and bool(self.mp_preapproval_id)

    def get_absolute_url(self):
        return reverse('donations:subscription_detail', args=[self.reference])


class SubscriptionPayment(models.Model):
    """Cobro recurrente de una suscripción (authorized_payment de Mercado Pago)."""

    subscription = models.ForeignKey(
        Subscription, on_delete=models.CASCADE, related_name='payments', verbose_name='suscripción',
    )
    mp_authorized_payment_id = models.CharField('ID de cobro MP', max_length=64, unique=True, null=True,
                                                blank=True)
    mp_payment_id = models.CharField('ID de pago MP', max_length=64, blank=True, db_index=True)
    amount = models.DecimalField('importe', max_digits=12, decimal_places=2, null=True, blank=True)
    status = models.CharField('estado del cobro', max_length=40, blank=True)
    payment_status = models.CharField('estado del pago', max_length=40, blank=True)
    payment_status_detail = models.CharField('detalle del pago', max_length=60, blank=True)
    debit_date = models.DateTimeField('fecha de cobro', null=True, blank=True)
    created_at = models.DateTimeField('registrado', auto_now_add=True)
    updated_at = models.DateTimeField('actualizado', auto_now=True)

    class Meta:
        verbose_name = 'cobro de suscripción'
        verbose_name_plural = 'cobros de suscripciones'
        ordering = ['-debit_date', '-created_at']

    def __str__(self):
        return f'Cobro {self.mp_authorized_payment_id or self.mp_payment_id} ({self.payment_status or self.status})'

    @property
    def is_approved(self):
        return self.payment_status == 'approved'


class WebhookEvent(models.Model):
    """Registro de notificaciones recibidas (auditoría + protección contra duplicados)."""

    class Result(models.TextChoices):
        RECEIVED = 'recibida', 'Recibida'
        PROCESSED = 'procesada', 'Procesada'
        IGNORED = 'ignorada', 'Ignorada'
        FAILED = 'error', 'Error'

    dedupe_key = models.CharField('clave de deduplicación', max_length=64, unique=True)
    topic = models.CharField('tópico', max_length=60, db_index=True)
    action = models.CharField('acción', max_length=80, blank=True)
    resource_id = models.CharField('ID del recurso', max_length=80, blank=True, db_index=True)
    request_id = models.CharField('x-request-id', max_length=120, blank=True)
    live_mode = models.BooleanField('producción', null=True, blank=True)
    payload = models.JSONField('contenido', default=dict, blank=True)
    result = models.CharField('resultado', max_length=20, choices=Result.choices, default=Result.RECEIVED)
    attempts = models.PositiveIntegerField('intentos recibidos', default=1)
    error = models.TextField('error', blank=True)
    received_at = models.DateTimeField('recibida', auto_now_add=True)
    processed_at = models.DateTimeField('procesada', null=True, blank=True)

    class Meta:
        verbose_name = 'notificación de Mercado Pago'
        verbose_name_plural = 'notificaciones de Mercado Pago'
        ordering = ['-received_at']

    def __str__(self):
        return f'{self.topic} {self.resource_id} ({self.get_result_display()})'
