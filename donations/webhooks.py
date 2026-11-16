"""Recepción y validación de notificaciones (Webhooks) de Mercado Pago."""
import hashlib
import json
import logging

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import F
from django.utils import timezone

from . import services
from .gateway import MercadoPagoError, get_gateway
from .models import WebhookEvent

logger = logging.getLogger('donations')

ORDER_TOPICS = {'order', 'orders', 'order_v2', 'orders_v2'}
PREAPPROVAL_TOPICS = {'subscription_preapproval', 'preapproval'}
AUTHORIZED_PAYMENT_TOPICS = {'subscription_authorized_payment', 'authorized_payment'}
PAYMENT_TOPICS = {'payment'}


class InvalidSignature(Exception):
    pass


def verify_signature(request, data_id):
    """Valida la cabecera ``x-signature`` con la clave secreta de Webhooks.

    Usa el validador oficial del SDK (HMAC-SHA256 sobre el manifiesto
    ``id:{data.id};request-id:{x-request-id};ts:{ts};``). Algunas guías de MP
    indican enviar ``data.id`` en minúsculas cuando es alfanumérico, así que se
    acepta la firma calculada con el valor tal cual o en minúsculas.
    """
    secret = settings.MERCADOPAGO_WEBHOOK_SECRET
    signature = request.headers.get('x-signature')
    request_id = request.headers.get('x-request-id')
    tolerance = settings.MERCADOPAGO_WEBHOOK_TOLERANCE or None

    from mercadopago.webhook import InvalidWebhookSignatureError, WebhookSignatureValidator

    candidates = [data_id]
    if data_id and data_id.lower() != data_id:
        candidates.append(data_id.lower())
    last_error = None
    for candidate in candidates:
        try:
            WebhookSignatureValidator.validate(
                signature, request_id, candidate, secret, tolerance_seconds=tolerance,
            )
            return True
        except InvalidWebhookSignatureError as exc:
            last_error = exc
    raise InvalidSignature(getattr(last_error, 'reason', last_error))


def parse_notification(request):
    try:
        body = json.loads(request.body or b'{}')
        if not isinstance(body, dict):
            body = {}
    except (ValueError, UnicodeDecodeError):
        body = {}
    data = body.get('data') if isinstance(body.get('data'), dict) else {}
    topic = (request.GET.get('type') or request.GET.get('topic') or body.get('type')
             or body.get('topic') or '').strip().lower()
    # data.id de la query string es el que se usa para la firma.
    query_data_id = request.GET.get('data.id') or request.GET.get('id') or ''
    resource_id = str(query_data_id or data.get('id') or '').strip()
    return {
        'topic': topic,
        'resource_id': resource_id,
        'query_data_id': query_data_id,
        'action': str(body.get('action') or ''),
        'notification_id': str(body.get('id') or ''),
        'live_mode': body.get('live_mode') if isinstance(body.get('live_mode'), bool) else None,
        'body': body,
    }


def _dedupe_key(info, request_id):
    raw = '|'.join([info['topic'], info['resource_id'], info['action'], info['notification_id'],
                    request_id or ''])
    return hashlib.sha256(raw.encode()).hexdigest()


def register_event(info, request_id):
    """Guarda la notificación. Devuelve (evento, ya_procesada)."""
    key = _dedupe_key(info, request_id)
    try:
        with transaction.atomic():
            event = WebhookEvent.objects.create(
                dedupe_key=key,
                topic=info['topic'][:60],
                action=info['action'][:80],
                resource_id=info['resource_id'][:80],
                request_id=(request_id or '')[:120],
                live_mode=info['live_mode'],
                payload=info['body'],
            )
        return event, False
    except IntegrityError:
        WebhookEvent.objects.filter(dedupe_key=key).update(attempts=F('attempts') + 1)
        event = WebhookEvent.objects.get(dedupe_key=key)
        return event, event.result in (WebhookEvent.Result.PROCESSED, WebhookEvent.Result.IGNORED)


def process_notification(info):
    """Consulta el recurso en Mercado Pago y actualiza la base. Devuelve True si se procesó."""
    topic, resource_id = info['topic'], info['resource_id']
    if not resource_id:
        return False
    gateway = get_gateway()
    if topic in ORDER_TOPICS:
        return services.apply_order_data(gateway.get_order(resource_id)) is not None
    if topic in PREAPPROVAL_TOPICS:
        return services.apply_preapproval_data(gateway.get_preapproval(resource_id)) is not None
    if topic in AUTHORIZED_PAYMENT_TOPICS:
        return services.apply_authorized_payment_data(gateway.get_authorized_payment(resource_id)) is not None
    if topic in PAYMENT_TOPICS:
        return services.apply_payment_data(gateway.get_payment(resource_id)) is not None
    return False


def handle(request):
    """Devuelve el código HTTP a responder a Mercado Pago."""
    info = parse_notification(request)
    request_id = request.headers.get('x-request-id', '')

    if settings.MERCADOPAGO_WEBHOOK_SECRET:
        try:
            verify_signature(request, info['query_data_id'] or info['resource_id'])
        except InvalidSignature as exc:
            logger.warning('Webhook con firma inválida (%s), request-id=%s', exc, request_id)
            return 401
    elif not settings.DEBUG:
        logger.error('MERCADOPAGO_WEBHOOK_SECRET no configurado: se rechazan las notificaciones.')
        return 503
    else:
        logger.warning('Webhook aceptado SIN validar firma (DEBUG sin MERCADOPAGO_WEBHOOK_SECRET).')

    if not info['topic']:
        return 200

    event, already_done = register_event(info, request_id)
    if already_done:
        logger.info('Notificación duplicada %s %s: ya procesada.', info['topic'], info['resource_id'])
        return 200

    try:
        processed = process_notification(info)
    except MercadoPagoError as exc:
        # Error temporal al consultar MP: respondemos 500 para que reintente.
        event.result = WebhookEvent.Result.FAILED
        event.error = str(exc)[:2000]
        event.save(update_fields=['result', 'error'])
        return 500

    event.result = WebhookEvent.Result.PROCESSED if processed else WebhookEvent.Result.IGNORED
    event.processed_at = timezone.now()
    event.error = ''
    event.save(update_fields=['result', 'processed_at', 'error'])
    return 200
