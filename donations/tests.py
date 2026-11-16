"""Tests del flujo de donaciones. Mercado Pago se reemplaza por un gateway falso:
no se hacen llamadas reales ni se usa dinero real.

Ejecutar:  python manage.py test
"""
import hashlib
import hmac
import json
import time
from decimal import Decimal
from io import StringIO
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse

from communities.models import Community, Donation as NeedDonation, Need

from . import services
from .gateway import MercadoPagoError
from .models import DonorTier, OneTimeDonation, Subscription, SubscriptionPayment, WebhookEvent
from .status import donation_status_from_order

User = get_user_model()
SECRET = 'clave-secreta-de-prueba'


class FakeGateway:
    """Simula la API de Mercado Pago guardando órdenes y suscripciones en memoria."""

    def __init__(self):
        self.orders = {}
        self.preapprovals = {}
        self.authorized = {}
        self.payments = {}
        self.created_payloads = []
        self.fail = False

    def _maybe_fail(self):
        if self.fail:
            raise MercadoPagoError('fallo simulado', 500)

    def create_order(self, payload, idempotency_key):
        self._maybe_fail()
        self.created_payloads.append((payload, idempotency_key))
        order_id = f'ORDTST{len(self.orders) + 1:04d}'
        self.orders[order_id] = {
            'id': order_id, 'status': 'created', 'status_detail': 'created',
            'external_reference': payload['external_reference'], 'total_amount': payload['total_amount'],
            'checkout_url': f'https://www.mercadopago.com.ar/checkout/v1/redirect?order_id={order_id}',
        }
        return dict(self.orders[order_id])

    def get_order(self, order_id):
        self._maybe_fail()
        return dict(self.orders[order_id])

    def set_order(self, order_id, status, detail, method=('visa', 'credit_card'), payment_id='PAY1', **extra):
        self.orders[order_id].update(status=status, status_detail=detail, transactions={'payments': [{
            'id': payment_id, 'status': status, 'status_detail': detail,
            'payment_method': {'id': method[0], 'type': method[1]},
        }]}, **extra)

    def create_preapproval(self, payload, idempotency_key):
        self._maybe_fail()
        self.created_payloads.append((payload, idempotency_key))
        pid = f'2c938084{len(self.preapprovals) + 1:04d}'
        self.preapprovals[pid] = {
            'id': pid, 'status': 'pending', 'external_reference': payload['external_reference'],
            'init_point': f'https://www.mercadopago.com.ar/subscriptions/checkout?preapproval_id={pid}',
            'auto_recurring': dict(payload['auto_recurring']),
        }
        return dict(self.preapprovals[pid])

    def get_preapproval(self, pid):
        self._maybe_fail()
        return dict(self.preapprovals[pid])

    def cancel_preapproval(self, pid):
        self._maybe_fail()
        self.preapprovals[pid]['status'] = 'cancelled'
        return dict(self.preapprovals[pid])

    def get_authorized_payment(self, aid):
        return dict(self.authorized[aid])

    def get_payment(self, payment_id):
        return dict(self.payments[payment_id])


def sign(data_id, request_id='req-1', ts=None, secret=SECRET):
    ts = ts or str(int(time.time()))
    manifest = f'id:{data_id};request-id:{request_id};ts:{ts};'
    digest = hmac.new(secret.encode(), manifest.encode(), hashlib.sha256).hexdigest()
    return {'HTTP_X_SIGNATURE': f'ts={ts},v1={digest}', 'HTTP_X_REQUEST_ID': request_id}


@override_settings(
    MERCADOPAGO_ACCESS_TOKEN='TEST-token', MERCADOPAGO_WEBHOOK_SECRET=SECRET,
    SITE_URL='https://semillas.test', DONATION_PRESET_AMOUNTS=[Decimal('5000'), Decimal('10000')],
    DONATION_MIN_AMOUNT=Decimal('500'), DONATION_MAX_AMOUNT=Decimal('1000000'),
)
class BaseCase(TestCase):
    def setUp(self):
        self.fake = FakeGateway()
        patcher = mock.patch('donations.services.get_gateway', return_value=self.fake)
        patcher2 = mock.patch('donations.webhooks.get_gateway', return_value=self.fake)
        patcher.start()
        patcher2.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(patcher2.stop)
        self.user = User.objects.create_user('ana@test.com', 'ana@test.com', 'clave-segura-123')
        self.other = User.objects.create_user('otro@test.com', 'otro@test.com', 'clave-segura-123')
        self.community = Community.objects.create(name='Comunidad Test', description='Desc', province='Salta',
                                                  population=100, email='c@test.com')
        self.need = Need.objects.create(community=self.community, title='Alimentos', description='d',
                                        category='Alimentos', target_amount=Decimal('100000'), is_urgent=True)
        self.client.force_login(self.user)

    def webhook(self, topic, data_id, signed=True, **headers):
        url = reverse('donations:webhook') + f'?data.id={data_id}&type={topic}'
        body = json.dumps({'action': f'{topic}.updated', 'type': topic, 'data': {'id': data_id}})
        extra = sign(data_id, **headers) if signed else {}
        return self.client.post(url, body, content_type='application/json', **extra)


class OneTimeDonationTests(BaseCase):
    def test_requires_login(self):
        self.client.logout()
        response = self.client.get(reverse('donations:one_time'))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('accounts:login'), response['Location'])

    def test_preset_amount_creates_order_and_redirects(self):
        response = self.client.post(reverse('donations:one_time'), {'amount_choice': '5000'})
        donation = OneTimeDonation.objects.get()
        self.assertRedirects(response, donation.checkout_url, fetch_redirect_response=False)
        self.assertEqual(donation.amount, Decimal('5000'))
        self.assertEqual(donation.user, self.user)
        self.assertEqual(donation.status, OneTimeDonation.Status.PENDING)
        payload, key = self.fake.created_payloads[0]
        self.assertEqual(payload['type'], 'online')
        self.assertEqual(payload['processing_mode'], 'manual')
        self.assertEqual(payload['total_amount'], '5000.00')
        self.assertEqual(payload['items'][0]['unit_price'], '5000.00')
        self.assertEqual(payload['config']['online']['auto_return'], 'all')
        self.assertTrue(payload['config']['online']['success_url'].startswith('https://semillas.test/donar/donacion/'))
        self.assertEqual(key, donation.reference.hex)

    def test_tampered_preset_amount_is_rejected(self):
        response = self.client.post(reverse('donations:one_time'), {'amount_choice': '1'})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(OneTimeDonation.objects.exists())

    def test_custom_amount_limits(self):
        for bad in ('100', '999999999', '-5', 'abc'):
            self.client.post(reverse('donations:one_time'), {'amount_choice': 'otro', 'custom_amount': bad})
        self.assertFalse(OneTimeDonation.objects.exists())
        self.client.post(reverse('donations:one_time'), {'amount_choice': 'otro', 'custom_amount': '7500'})
        self.assertEqual(OneTimeDonation.objects.get().amount, Decimal('7500'))

    def test_need_amount_cannot_exceed_remaining(self):
        self.need.target_amount = Decimal('3000')
        self.need.save()
        self.client.post(reverse('donations:one_time'), {'amount_choice': '5000', 'need': self.need.pk})
        self.assertFalse(OneTimeDonation.objects.exists())

    def test_return_url_params_do_not_approve(self):
        """Volver del checkout con ?status=approved NO aprueba: manda la API."""
        self.client.post(reverse('donations:one_time'), {'amount_choice': '5000'})
        donation = OneTimeDonation.objects.get()
        url = donation.get_absolute_url() + '?status=approved&payment_id=123&collection_status=approved'
        response = self.client.get(url)
        donation.refresh_from_db()
        self.assertEqual(donation.status, OneTimeDonation.Status.PENDING)
        self.assertContains(response, 'DONACIÓN PENDIENTE')

    def test_return_page_shows_approved_after_api_confirms(self):
        self.client.post(reverse('donations:one_time'), {'amount_choice': '5000', 'need': self.need.pk})
        donation = OneTimeDonation.objects.get()
        self.fake.set_order(donation.mp_order_id, 'processed', 'accredited')
        response = self.client.get(donation.get_absolute_url())
        self.assertContains(response, 'DONACIÓN APROBADA')
        donation.refresh_from_db()
        self.assertEqual(donation.payment_method, 'visa')
        self.assertIsNotNone(donation.need_donation)
        self.assertEqual(self.need.raised_amount, Decimal('5000'))

    def test_rejected_and_pending_pages(self):
        self.client.post(reverse('donations:one_time'), {'amount_choice': '5000'})
        donation = OneTimeDonation.objects.get()
        self.fake.set_order(donation.mp_order_id, 'failed', 'rejected_by_issuer')
        self.assertContains(self.client.get(donation.get_absolute_url()), 'DONACIÓN RECHAZADA')

    def test_other_user_cannot_see_donation(self):
        self.client.post(reverse('donations:one_time'), {'amount_choice': '5000'})
        donation = OneTimeDonation.objects.get()
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(donation.get_absolute_url()).status_code, 403)

    def test_mercadopago_error_shows_message_and_marks_error(self):
        self.fake.fail = True
        response = self.client.post(reverse('donations:one_time'), {'amount_choice': '5000'}, follow=True)
        self.assertContains(response, 'No pudimos conectar con Mercado Pago')
        self.assertEqual(OneTimeDonation.objects.get().status, OneTimeDonation.Status.ERROR)

    @override_settings(MERCADOPAGO_ACCESS_TOKEN='')
    def test_not_configured(self):
        from .gateway import MercadoPagoGateway, MercadoPagoNotConfigured

        with self.assertRaises(MercadoPagoNotConfigured):
            MercadoPagoGateway()
        with mock.patch('donations.services.get_gateway', side_effect=MercadoPagoNotConfigured('x')):
            response = self.client.post(reverse('donations:one_time'), {'amount_choice': '5000'}, follow=True)
        self.assertContains(response, 'todavía no están habilitadas')

    def test_csrf_required(self):
        client = self.client_class(enforce_csrf_checks=True)
        client.force_login(self.user)
        response = client.post(reverse('donations:one_time'), {'amount_choice': '5000'})
        self.assertEqual(response.status_code, 403)


class StatusMappingTests(TestCase):
    def test_order_status_mapping(self):
        S = OneTimeDonation.Status
        self.assertEqual(donation_status_from_order('processed', 'accredited'), S.APPROVED)
        self.assertEqual(donation_status_from_order('processed', 'partially_refunded'), S.PARTIALLY_REFUNDED)
        self.assertEqual(donation_status_from_order('failed', 'high_risk'), S.REJECTED)
        self.assertEqual(donation_status_from_order('processing', 'in_process'), S.IN_PROCESS)
        self.assertEqual(donation_status_from_order('action_required', 'waiting_payment'), S.PENDING)
        self.assertEqual(donation_status_from_order('canceled', 'canceled'), S.CANCELLED)
        self.assertEqual(donation_status_from_order('canceled', 'expired'), S.EXPIRED)
        self.assertEqual(donation_status_from_order('refunded', 'refunded'), S.REFUNDED)
        self.assertEqual(donation_status_from_order('algo_nuevo', ''), S.PENDING)


class WebhookTests(BaseCase):
    def _create_donation(self, **data):
        self.client.post(reverse('donations:one_time'), {'amount_choice': '5000', **data})
        return OneTimeDonation.objects.get()

    def test_valid_order_webhook_approves_once(self):
        donation = self._create_donation(need=self.need.pk)
        self.fake.set_order(donation.mp_order_id, 'processed', 'accredited')
        self.client.logout()  # el webhook no depende de la sesión del usuario

        self.assertEqual(self.webhook('order', donation.mp_order_id).status_code, 200)
        donation.refresh_from_db()
        self.assertEqual(donation.status, OneTimeDonation.Status.APPROVED)
        self.assertIsNotNone(donation.approved_at)

        # Mismo aviso repetido (mismo x-request-id) y otro aviso nuevo: no se duplica nada.
        self.assertEqual(self.webhook('order', donation.mp_order_id).status_code, 200)
        self.assertEqual(self.webhook('order', donation.mp_order_id, request_id='req-2').status_code, 200)
        self.assertEqual(NeedDonation.objects.filter(need=self.need).count(), 1)
        self.assertEqual(self.need.raised_amount, Decimal('5000'))
        event = WebhookEvent.objects.get(request_id='req-1')
        self.assertEqual(event.attempts, 2)
        self.assertEqual(event.result, WebhookEvent.Result.PROCESSED)

    def test_invalid_signature_rejected(self):
        donation = self._create_donation()
        self.fake.set_order(donation.mp_order_id, 'processed', 'accredited')
        url = reverse('donations:webhook') + f'?data.id={donation.mp_order_id}&type=order'
        bad = sign(donation.mp_order_id, secret='otra-clave')
        response = self.client.post(url, '{}', content_type='application/json', **bad)
        self.assertEqual(response.status_code, 401)
        self.assertEqual(self.webhook('order', donation.mp_order_id, signed=False).status_code, 401)
        donation.refresh_from_db()
        self.assertEqual(donation.status, OneTimeDonation.Status.PENDING)

    def test_signature_with_lowercase_data_id_accepted(self):
        donation = self._create_donation()
        self.fake.set_order(donation.mp_order_id, 'processed', 'accredited')
        url = reverse('donations:webhook') + f'?data.id={donation.mp_order_id}&type=order'
        headers = sign(donation.mp_order_id.lower())
        self.assertEqual(self.client.post(url, '{}', content_type='application/json', **headers).status_code, 200)

    def test_amount_mismatch_is_not_approved(self):
        donation = self._create_donation(need=self.need.pk)
        self.fake.set_order(donation.mp_order_id, 'processed', 'accredited', total_amount='1.00')
        self.webhook('order', donation.mp_order_id)
        donation.refresh_from_db()
        self.assertNotEqual(donation.status, OneTimeDonation.Status.APPROVED)
        self.assertEqual(self.need.raised_amount, Decimal('0'))

    def test_refund_removes_need_progress(self):
        donation = self._create_donation(need=self.need.pk)
        self.fake.set_order(donation.mp_order_id, 'processed', 'accredited')
        self.webhook('order', donation.mp_order_id)
        self.fake.set_order(donation.mp_order_id, 'refunded', 'refunded')
        self.webhook('order', donation.mp_order_id, request_id='req-3')
        donation.refresh_from_db()
        self.assertEqual(donation.status, OneTimeDonation.Status.REFUNDED)
        self.assertEqual(self.need.raised_amount, Decimal('0'))

    def test_api_failure_returns_500_for_retry(self):
        donation = self._create_donation()
        self.fake.fail = True
        self.assertEqual(self.webhook('order', donation.mp_order_id).status_code, 500)
        self.fake.fail = False
        self.fake.set_order(donation.mp_order_id, 'processed', 'accredited')
        # El reintento de MP (mismo request-id) se vuelve a procesar porque antes falló.
        self.assertEqual(self.webhook('order', donation.mp_order_id).status_code, 200)
        donation.refresh_from_db()
        self.assertEqual(donation.status, OneTimeDonation.Status.APPROVED)

    def test_unknown_topic_and_resource_ignored(self):
        self.assertEqual(self.webhook('point_integration_wh', 'X1').status_code, 200)
        self.fake.orders['ORDOTRA'] = {'id': 'ORDOTRA', 'status': 'processed', 'status_detail': 'accredited',
                                       'external_reference': 'no-es-nuestra'}
        self.assertEqual(self.webhook('order', 'ORDOTRA').status_code, 200)
        self.assertEqual(WebhookEvent.objects.get(resource_id='ORDOTRA').result, WebhookEvent.Result.IGNORED)

    def test_get_not_allowed(self):
        self.assertEqual(self.client.get(reverse('donations:webhook')).status_code, 405)

    @override_settings(MERCADOPAGO_WEBHOOK_SECRET='', DEBUG=False)
    def test_missing_secret_in_production_rejects(self):
        self.assertEqual(self.webhook('order', 'X', signed=False).status_code, 503)


class SubscriptionTests(BaseCase):
    def setUp(self):
        super().setUp()
        self.tier = DonorTier.objects.get(slug='donador-solidario')

    def _subscribe(self):
        response = self.client.post(reverse('donations:subscribe', args=[self.tier.slug]),
                                    {'payer_email': 'comprador@test.com', 'accept': 'on'})
        return response, Subscription.objects.get()

    def test_four_tiers_seeded(self):
        self.assertEqual(DonorTier.objects.filter(is_active=True).count(), 4)
        response = self.client.get(reverse('donations:monthly'))
        for name in ('Donador Inicial', 'Donador Solidario', 'Donador Colaborador', 'Donador Padrino'):
            self.assertContains(response, name)

    def test_subscribe_creates_preapproval_with_backend_amount(self):
        response, sub = self._subscribe()
        self.assertRedirects(response, sub.init_point, fetch_redirect_response=False)
        payload, _ = self.fake.created_payloads[0]
        self.assertEqual(payload['auto_recurring']['transaction_amount'], 10000.0)
        self.assertEqual(payload['auto_recurring']['frequency_type'], 'months')
        self.assertEqual(payload['status'], 'pending')
        self.assertEqual(payload['payer_email'], 'comprador@test.com')
        self.assertEqual(sub.user, self.user)
        self.assertEqual(sub.status, Subscription.Status.PENDING)

    def test_amount_from_post_is_ignored(self):
        self.client.post(reverse('donations:subscribe', args=[self.tier.slug]),
                         {'payer_email': 'a@test.com', 'accept': 'on', 'amount': '1'})
        self.assertEqual(Subscription.objects.get().amount, Decimal('10000'))

    def test_must_accept(self):
        self.client.post(reverse('donations:subscribe', args=[self.tier.slug]), {'payer_email': 'a@test.com'})
        self.assertFalse(Subscription.objects.exists())

    def test_webhook_activates_and_records_payments(self):
        _, sub = self._subscribe()
        pid = sub.mp_preapproval_id
        self.fake.preapprovals[pid].update(status='authorized', next_payment_date='2026-12-16T10:00:00.000-03:00')
        self.assertEqual(self.webhook('subscription_preapproval', pid).status_code, 200)
        sub.refresh_from_db()
        self.assertEqual(sub.status, Subscription.Status.AUTHORIZED)
        self.assertIsNotNone(sub.started_at)
        self.assertEqual(sub.next_payment_date.day, 16)

        self.fake.authorized['7001'] = {'id': 7001, 'preapproval_id': pid, 'transaction_amount': 10000,
                                        'status': 'processed', 'debit_date': '2026-11-16T10:00:00.000-03:00',
                                        'payment': {'id': 9001, 'status': 'approved', 'status_detail': 'accredited'}}
        self.webhook('subscription_authorized_payment', '7001')
        self.webhook('subscription_authorized_payment', '7001', request_id='req-9')
        self.assertEqual(SubscriptionPayment.objects.count(), 1)
        payment = SubscriptionPayment.objects.get()
        self.assertTrue(payment.is_approved)
        self.assertEqual(payment.mp_payment_id, '9001')

        response = self.client.get(reverse('donations:my_activity'))
        self.assertContains(response, 'Donador Solidario')
        self.assertContains(response, 'Activa')

    def test_cancel_subscription(self):
        _, sub = self._subscribe()
        self.fake.preapprovals[sub.mp_preapproval_id]['status'] = 'authorized'
        services.refresh_subscription(sub)
        response = self.client.post(reverse('donations:subscription_cancel', args=[sub.reference]))
        self.assertRedirects(response, sub.get_absolute_url(), fetch_redirect_response=False)
        sub.refresh_from_db()
        self.assertEqual(sub.status, Subscription.Status.CANCELLED)
        self.assertIsNotNone(sub.cancelled_at)
        self.assertEqual(self.fake.preapprovals[sub.mp_preapproval_id]['status'], 'cancelled')

    def test_other_user_cannot_cancel(self):
        _, sub = self._subscribe()
        self.client.force_login(self.other)
        response = self.client.post(reverse('donations:subscription_cancel', args=[sub.reference]))
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.fake.preapprovals[sub.mp_preapproval_id]['status'], 'pending')

    def test_cancel_failure_keeps_state(self):
        _, sub = self._subscribe()
        self.fake.fail = True
        self.client.post(reverse('donations:subscription_cancel', args=[sub.reference]))
        sub.refresh_from_db()
        self.assertEqual(sub.status, Subscription.Status.PENDING)


class SyncCommandTests(BaseCase):
    def test_command_updates_pending(self):
        self.client.post(reverse('donations:one_time'), {'amount_choice': '5000'})
        donation = OneTimeDonation.objects.get()
        self.fake.set_order(donation.mp_order_id, 'processed', 'accredited')
        call_command('sincronizar_mercadopago', stdout=StringIO())
        donation.refresh_from_db()
        self.assertEqual(donation.status, OneTimeDonation.Status.APPROVED)
