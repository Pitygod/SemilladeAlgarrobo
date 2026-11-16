"""Lógica de negocio de donaciones: crear órdenes/suscripciones y sincronizar estados.

Regla central: el estado de una donación o suscripción SOLO se modifica con datos
obtenidos directamente de la API de Mercado Pago (nunca con parámetros que trae
el navegador al volver del checkout).
"""
import logging
import uuid
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from communities.models import Donation as NeedDonation

from .gateway import MercadoPagoError, get_gateway
from .models import OneTimeDonation, Subscription, SubscriptionPayment
from .status import donation_status_from_order, subscription_status_from_preapproval

logger = logging.getLogger('donations')

D = OneTimeDonation.Status


def absolute_url(path):
    return f'{settings.SITE_URL}{path}'


def _money(value):
    """Convierte importes de MP (string o número) a Decimal con 2 decimales."""
    try:
        return Decimal(str(value)).quantize(Decimal('0.01'))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _format_amount(amount):
    return f'{Decimal(amount).quantize(Decimal("0.01"))}'


def _parse_dt(value):
    if not value:
        return None
    try:
        return parse_datetime(str(value))
    except ValueError:
        return None


# =============================================================================
# Donación única (Checkout Pro mediante Orders API)
# =============================================================================
def build_order_payload(donation):
    return_url = absolute_url(donation.get_absolute_url())
    title = 'Donación a Semillas del Algarrobo'
    if donation.community:
        title = f'Donación para {donation.community.name}'[:250]
    online = {
        'success_url': return_url,
        'failure_url': return_url,
        'pending_url': return_url,
    }
    # auto_return solo es aceptado con URLs públicas https.
    if return_url.startswith('https://'):
        online['auto_return'] = 'all'
    amount = _format_amount(donation.amount)
    return {
        'type': 'online',
        'processing_mode': 'manual',
        'external_reference': donation.reference.hex,
        'total_amount': amount,
        'description': title,
        'items': [{
            'external_code': f'DONACION-{donation.need_id or donation.community_id or "GENERAL"}',
            'title': title,
            'quantity': 1,
            'unit_price': amount,
        }],
        'config': {
            'statement_descriptor': settings.MERCADOPAGO_STATEMENT_DESCRIPTOR,
            'online': online,
        },
    }


def create_one_time_donation(user, amount, community=None, need=None):
    """Registra la donación y crea la orden en Mercado Pago.

    El importe ya fue validado por el formulario del backend. Devuelve la
    donación con ``checkout_url`` para redirigir al usuario.
    """
    donation = OneTimeDonation.objects.create(
        user=user if user and user.is_authenticated else None,
        community=community or (need.community if need else None),
        need=need,
        amount=amount,
        currency=settings.MERCADOPAGO_CURRENCY,
    )
    try:
        gateway = get_gateway()
        order = gateway.create_order(build_order_payload(donation), idempotency_key=donation.reference.hex)
    except MercadoPagoError as exc:
        donation.status = D.ERROR
        donation.error_message = str(exc)[:255]
        donation.save(update_fields=['status', 'error_message', 'updated_at'])
        raise

    donation.mp_order_id = order.get('id')
    donation.checkout_url = order.get('checkout_url') or ''
    donation.mp_status = order.get('status') or ''
    donation.mp_status_detail = order.get('status_detail') or ''
    donation.save(update_fields=['mp_order_id', 'checkout_url', 'mp_status', 'mp_status_detail', 'updated_at'])
    if not donation.checkout_url:
        raise MercadoPagoError('Mercado Pago no devolvió la URL de checkout.')
    return donation


def _first_payment(order):
    payments = ((order.get('transactions') or {}).get('payments')) or []
    return payments[0] if payments else {}


@transaction.atomic
def apply_order_data(order):
    """Actualiza la donación local a partir de una orden obtenida de la API de MP.

    Es idempotente: procesar la misma orden varias veces deja el mismo resultado
    y nunca registra dos veces el aporte en la necesidad.
    """
    order_id = order.get('id')
    reference = order.get('external_reference') or ''
    qs = OneTimeDonation.objects.select_for_update()
    donation = None
    if order_id:
        donation = qs.filter(mp_order_id=order_id).first()
    if donation is None and _as_uuid(reference):
        donation = qs.filter(reference=_as_uuid(reference)).first()
    if donation is None:
        logger.info('Orden %s sin donación asociada (external_reference=%s); se ignora.', order_id, reference)
        return None

    new_status = donation_status_from_order(order.get('status'), order.get('status_detail'))

    # Control de importes: la orden debe coincidir con lo registrado en el backend.
    total = _money(order.get('total_amount'))
    if total is not None and total != donation.amount:
        logger.error('Importe inconsistente en orden %s: MP=%s, local=%s', order_id, total, donation.amount)
        donation.error_message = f'Importe inconsistente: Mercado Pago informó {total}.'
        if new_status == D.APPROVED:
            new_status = D.IN_PROCESS  # requiere revisión manual; no se acredita

    payment = _first_payment(order)
    method = payment.get('payment_method') or {}

    donation.mp_order_id = donation.mp_order_id or order_id
    donation.mp_status = order.get('status') or ''
    donation.mp_status_detail = order.get('status_detail') or ''
    donation.mp_payment_id = str(payment.get('id') or donation.mp_payment_id or '')
    donation.payment_method = method.get('id') or donation.payment_method
    donation.payment_type = method.get('type') or donation.payment_type
    donation.status = new_status
    donation.last_synced_at = timezone.now()
    if new_status in (D.APPROVED, D.PARTIALLY_REFUNDED) and not donation.approved_at:
        donation.approved_at = timezone.now()

    _sync_need_donation(donation)
    donation.save()
    return donation


def _as_uuid(value):
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError):
        return None


def _sync_need_donation(donation):
    """Refleja el aporte aprobado en el progreso de la necesidad (una sola vez)."""
    if not donation.need_id:
        return
    counts = donation.status in (D.APPROVED, D.PARTIALLY_REFUNDED)
    if counts and donation.need_donation_id is None:
        donation.need_donation = NeedDonation.objects.create(
            need=donation.need, donor=donation.user, amount=donation.amount,
        )
    elif donation.status == D.REFUNDED and donation.need_donation_id:
        # Reembolso total: el dinero ya no está disponible para la necesidad.
        need_donation = donation.need_donation
        donation.need_donation = None
        need_donation.delete()


def refresh_donation(donation):
    """Consulta la orden en Mercado Pago y actualiza la donación."""
    if not donation.mp_order_id:
        return donation
    order = get_gateway().get_order(donation.mp_order_id)
    return apply_order_data(order) or donation


# =============================================================================
# Suscripciones (preapproval sin plan, con pago pendiente)
# =============================================================================
def build_preapproval_payload(subscription):
    return {
        'reason': f'{settings.SITE_NAME} - {subscription.tier_name}'[:255],
        'external_reference': subscription.reference.hex,
        'payer_email': subscription.payer_email,
        'auto_recurring': {
            'frequency': subscription.frequency_months,
            'frequency_type': 'months',
            'transaction_amount': float(subscription.amount),
            'currency_id': subscription.currency,
        },
        'back_url': absolute_url(subscription.get_absolute_url()),
        'status': 'pending',
    }


def create_subscription(user, tier, payer_email):
    """Registra la suscripción y la crea en Mercado Pago. El importe sale del nivel (backend)."""
    subscription = Subscription.objects.create(
        user=user,
        tier=tier,
        tier_name=tier.name,
        amount=tier.amount,
        frequency_months=tier.frequency_months,
        currency=settings.MERCADOPAGO_CURRENCY,
        payer_email=payer_email,
    )
    try:
        data = get_gateway().create_preapproval(
            build_preapproval_payload(subscription), idempotency_key=subscription.reference.hex,
        )
    except MercadoPagoError as exc:
        subscription.status = Subscription.Status.ERROR
        subscription.error_message = str(exc)[:255]
        subscription.save(update_fields=['status', 'error_message', 'updated_at'])
        raise

    subscription.mp_preapproval_id = data.get('id')
    subscription.init_point = data.get('init_point') or ''
    subscription.save(update_fields=['mp_preapproval_id', 'init_point', 'updated_at'])
    apply_preapproval_data(data)
    subscription.refresh_from_db()
    if not subscription.init_point:
        raise MercadoPagoError('Mercado Pago no devolvió la URL de autorización.')
    return subscription


@transaction.atomic
def apply_preapproval_data(data):
    preapproval_id = data.get('id')
    reference = _as_uuid(data.get('external_reference'))
    qs = Subscription.objects.select_for_update()
    subscription = qs.filter(mp_preapproval_id=preapproval_id).first() if preapproval_id else None
    if subscription is None and reference:
        subscription = qs.filter(reference=reference).first()
    if subscription is None:
        logger.info('Suscripción MP %s sin registro local; se ignora.', preapproval_id)
        return None

    auto = data.get('auto_recurring') or {}
    mp_amount = _money(auto.get('transaction_amount'))
    if mp_amount is not None and mp_amount != subscription.amount:
        logger.warning('Importe de suscripción %s distinto en MP (%s) y local (%s).',
                       preapproval_id, mp_amount, subscription.amount)

    new_status = subscription_status_from_preapproval(data.get('status'))
    subscription.mp_preapproval_id = subscription.mp_preapproval_id or preapproval_id
    subscription.mp_status = data.get('status') or ''
    subscription.status = new_status
    subscription.init_point = data.get('init_point') or subscription.init_point
    subscription.next_payment_date = _parse_dt(data.get('next_payment_date'))
    if new_status == Subscription.Status.AUTHORIZED and not subscription.started_at:
        subscription.started_at = _parse_dt(auto.get('start_date')) or timezone.now()
    if new_status == Subscription.Status.CANCELLED and not subscription.cancelled_at:
        subscription.cancelled_at = timezone.now()
        subscription.next_payment_date = None
    subscription.last_synced_at = timezone.now()
    subscription.save()
    return subscription


def refresh_subscription(subscription):
    if not subscription.mp_preapproval_id:
        return subscription
    data = get_gateway().get_preapproval(subscription.mp_preapproval_id)
    return apply_preapproval_data(data) or subscription


def cancel_subscription(subscription):
    """Cancela la suscripción en Mercado Pago y luego actualiza la base local."""
    if not subscription.can_be_cancelled:
        raise ValueError('Esta suscripción no se puede cancelar.')
    data = get_gateway().cancel_preapproval(subscription.mp_preapproval_id)
    updated = apply_preapproval_data(data) if data.get('id') else None
    if updated is None or updated.status != Subscription.Status.CANCELLED:
        # Confirmamos con una consulta directa por si la respuesta vino incompleta.
        updated = refresh_subscription(subscription)
    return updated


@transaction.atomic
def apply_authorized_payment_data(data):
    """Registra/actualiza un cobro recurrente (idempotente por ID de MP)."""
    authorized_id = str(data.get('id') or '')
    preapproval_id = data.get('preapproval_id')
    subscription = Subscription.objects.filter(mp_preapproval_id=preapproval_id).first()
    if subscription is None or not authorized_id:
        logger.info('Cobro %s de suscripción desconocida %s; se ignora.', authorized_id, preapproval_id)
        return None

    payment = data.get('payment') or {}
    record, _ = SubscriptionPayment.objects.select_for_update().get_or_create(
        mp_authorized_payment_id=authorized_id,
        defaults={'subscription': subscription},
    )
    record.mp_payment_id = str(payment.get('id') or record.mp_payment_id or '')
    record.amount = _money(data.get('transaction_amount')) or record.amount
    record.status = data.get('status') or ''
    record.payment_status = payment.get('status') or record.payment_status
    record.payment_status_detail = payment.get('status_detail') or record.payment_status_detail
    record.debit_date = _parse_dt(data.get('debit_date') or data.get('date_created')) or record.debit_date
    record.save()
    return record


def apply_payment_data(payment):
    """Notificaciones del tópico ``payment``.

    Se usan como respaldo: si el pago pertenece a una donación única se vuelve a
    consultar su orden; si pertenece a una suscripción se registra el cobro.
    """
    reference = _as_uuid(payment.get('external_reference'))
    if reference is None:
        return None
    donation = OneTimeDonation.objects.filter(reference=reference).first()
    if donation:
        return refresh_donation(donation)

    subscription = Subscription.objects.filter(reference=reference).first()
    if subscription:
        payment_id = str(payment.get('id') or '')
        with transaction.atomic():
            record = (SubscriptionPayment.objects.select_for_update()
                      .filter(subscription=subscription, mp_payment_id=payment_id).first())
            if record is None:
                record = SubscriptionPayment(subscription=subscription, mp_payment_id=payment_id)
            record.amount = _money(payment.get('transaction_amount')) or record.amount
            record.payment_status = payment.get('status') or ''
            record.payment_status_detail = payment.get('status_detail') or ''
            record.debit_date = _parse_dt(payment.get('date_approved') or payment.get('date_created'))
            record.save()
        return record
    return None
