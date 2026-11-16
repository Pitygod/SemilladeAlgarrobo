"""Acceso a la API de Mercado Pago mediante el SDK oficial (``mercadopago`` >= 3.6).

Toda llamada a Mercado Pago del proyecto pasa por :class:`MercadoPagoGateway`,
así las credenciales se leen en un único lugar (settings / variables de entorno)
y los tests pueden reemplazar el gateway por uno falso.

Endpoints utilizados:

* ``POST /v1/orders``                 Checkout Pro mediante Orders API (donación única)
* ``GET  /v1/orders/{id}``            estado real de la orden
* ``POST /preapproval``               suscripción sin plan, con pago pendiente (``init_point``)
* ``GET  /preapproval/{id}``          estado real de la suscripción
* ``PUT  /preapproval/{id}``          cancelación (``status=cancelled``)
* ``GET  /authorized_payments/{id}``  cobros recurrentes de una suscripción
* ``GET  /v1/payments/{id}``          pagos (notificaciones del tópico ``payment``)
"""
import logging

from django.conf import settings

logger = logging.getLogger('donations')


class MercadoPagoError(Exception):
    """Error al comunicarse con Mercado Pago (credenciales, red, validación)."""

    def __init__(self, message, status=None, response=None):
        super().__init__(message)
        self.status = status
        self.response = response or {}


class MercadoPagoNotConfigured(MercadoPagoError):
    """Falta MERCADOPAGO_ACCESS_TOKEN en el entorno."""


class MercadoPagoGateway:
    def __init__(self, access_token=None):
        self.access_token = access_token or settings.MERCADOPAGO_ACCESS_TOKEN
        if not self.access_token:
            raise MercadoPagoNotConfigured(
                'Mercado Pago no está configurado: definí MERCADOPAGO_ACCESS_TOKEN en el archivo .env.'
            )
        # Import diferido: el resto del sitio funciona aunque el SDK no esté instalado.
        import mercadopago

        self._mp = mercadopago
        self._sdk = mercadopago.SDK(self.access_token)

    # ------------------------------------------------------------------ helpers
    def _options(self, idempotency_key=None):
        if not idempotency_key:
            return None
        from mercadopago.config import RequestOptions

        # La clave de idempotencia evita que un reintento cree dos órdenes/suscripciones.
        return RequestOptions(
            access_token=self.access_token,
            custom_headers={'x-idempotency-key': str(idempotency_key)[:64]},
        )

    def _call(self, description, func, *args, expected=(200, 201), **kwargs):
        try:
            result = func(*args, **kwargs)
        except self._mp.errors.MercadoPagoError as exc:  # errores tipados del SDK
            logger.warning('Mercado Pago %s falló: %s', description, exc)
            raise MercadoPagoError(str(exc), getattr(exc, 'status_code', None), getattr(exc, 'response', None)) from exc
        except Exception as exc:  # red, timeouts, JSON inválido
            logger.exception('Error de conexión con Mercado Pago (%s)', description)
            raise MercadoPagoError(f'No se pudo conectar con Mercado Pago: {exc}') from exc

        status = result.get('status')
        response = result.get('response') or {}
        if status not in expected:
            message = response.get('message') or response.get('error') or 'respuesta inesperada'
            logger.warning('Mercado Pago %s devolvió %s: %s', description, status, response)
            raise MercadoPagoError(f'Mercado Pago respondió {status}: {message}', status, response)
        return response

    # ------------------------------------------------------------------- orders
    def create_order(self, payload, idempotency_key):
        return self._call('crear orden', self._sdk.order().create, payload,
                          request_options=self._options(idempotency_key))

    def get_order(self, order_id):
        return self._call('consultar orden', self._sdk.order().get, order_id)

    # ------------------------------------------------------------ subscriptions
    def create_preapproval(self, payload, idempotency_key):
        return self._call('crear suscripción', self._sdk.preapproval().create, payload,
                          request_options=self._options(idempotency_key))

    def get_preapproval(self, preapproval_id):
        return self._call('consultar suscripción', self._sdk.preapproval().get, preapproval_id)

    def cancel_preapproval(self, preapproval_id):
        return self._call('cancelar suscripción', self._sdk.preapproval().update,
                          preapproval_id, {'status': 'cancelled'})

    def get_authorized_payment(self, authorized_payment_id):
        return self._call('consultar cobro de suscripción', self._sdk.invoice().get, authorized_payment_id)

    # ----------------------------------------------------------------- payments
    def get_payment(self, payment_id):
        return self._call('consultar pago', self._sdk.payment().get, payment_id)


def get_gateway():
    """Punto único de creación del gateway (los tests lo reemplazan con mock)."""
    return MercadoPagoGateway()
