"""Traducción de estados de Mercado Pago a los estados internos del sitio."""
from .models import OneTimeDonation, Subscription

D = OneTimeDonation.Status
S = Subscription.Status

# Orders API (Checkout Pro). status / status_detail documentados en:
# https://www.mercadopago.com.ar/developers/es/docs/checkout-pro-orders/payment-management/status/order-status
ORDER_STATUS_MAP = {
    'created': D.PENDING,
    'action_required': D.PENDING,
    'processing': D.IN_PROCESS,
    'processed': D.APPROVED,
    'failed': D.REJECTED,
    'canceled': D.CANCELLED,
    'cancelled': D.CANCELLED,
    'expired': D.EXPIRED,
    'refunded': D.REFUNDED,
    'charged_back': D.REFUNDED,
}


def donation_status_from_order(status, status_detail=''):
    status = (status or '').lower()
    status_detail = (status_detail or '').lower()
    if status_detail == 'expired':
        return D.EXPIRED
    if status_detail == 'refunded':
        return D.REFUNDED
    if status_detail == 'partially_refunded':
        return D.PARTIALLY_REFUNDED
    if status == 'processed' and status_detail not in ('', 'accredited'):
        # "processed" con un detalle desconocido: no lo damos por aprobado.
        return D.IN_PROCESS
    return ORDER_STATUS_MAP.get(status, D.PENDING)


# Suscripciones (preapproval): pending, authorized, paused, cancelled.
PREAPPROVAL_STATUS_MAP = {
    'pending': S.PENDING,
    'authorized': S.AUTHORIZED,
    'paused': S.PAUSED,
    'cancelled': S.CANCELLED,
    'canceled': S.CANCELLED,
    'rejected': S.REJECTED,
}


def subscription_status_from_preapproval(status):
    return PREAPPROVAL_STATUS_MAP.get((status or '').lower(), S.PENDING)


PAYMENT_STATUS_LABELS = {
    'approved': 'Aprobado',
    'pending': 'Pendiente',
    'in_process': 'En proceso',
    'rejected': 'Rechazado',
    'cancelled': 'Cancelado',
    'refunded': 'Reembolsado',
    'charged_back': 'Contracargo',
    'scheduled': 'Programado',
    'processed': 'Procesado',
    'recycling': 'Reintentando',
}
