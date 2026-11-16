import shutil
import tempfile
from decimal import Decimal
from io import BytesIO

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image

from .models import Community, CommunityImage, Donation, Need
from .priority import featured_and_others, need_score

User = get_user_model()
MEDIA = tempfile.mkdtemp()


def image_file(name='foto.jpg', color='green'):
    buffer = BytesIO()
    Image.new('RGB', (40, 30), color).save(buffer, 'JPEG')
    return SimpleUploadedFile(name, buffer.getvalue(), content_type='image/jpeg')


@override_settings(MEDIA_ROOT=MEDIA)
class CommunityTestBase(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(MEDIA, ignore_errors=True)

    def make_community(self, name, **kwargs):
        defaults = dict(description='Desc', province='Salta', population=10, email='c@test.com')
        defaults.update(kwargs)
        return Community.objects.create(name=name, **defaults)


class PriorityTests(CommunityTestBase):
    def test_community_with_more_urgent_needs_is_featured(self):
        calm = self.make_community('Calma')
        Need.objects.create(community=calm, title='Libros', description='d', category='Educación',
                            target_amount=Decimal('1000'))
        urgent = self.make_community('Urgente')
        Need.objects.create(community=urgent, title='Comida', description='d', category='Alimentos',
                            target_amount=Decimal('1000'), is_urgent=True)
        featured, others = featured_and_others()
        self.assertEqual(featured, urgent)
        self.assertEqual(others, [calm])

    def test_manual_featured_overrides_score(self):
        urgent = self.make_community('Urgente')
        Need.objects.create(community=urgent, title='Comida', description='d', category='Alimentos',
                            target_amount=Decimal('1000'), is_urgent=True)
        manual = self.make_community('Manual', is_featured=True)
        featured, _ = featured_and_others()
        self.assertEqual(featured, manual)

    def test_completed_needs_do_not_count(self):
        community = self.make_community('C')
        need = Need.objects.create(community=community, title='x', description='d', category='Salud',
                                   target_amount=Decimal('1000'), status=Need.Status.COMPLETED)
        self.assertEqual(need_score(need), 0)

    def test_funding_reduces_score(self):
        community = self.make_community('C')
        need = Need.objects.create(community=community, title='x', description='d', category='Salud',
                                   target_amount=Decimal('1000'))
        before = need_score(need)
        Donation.objects.create(need=need, amount=Decimal('500'))
        self.assertLess(need_score(need), before)


class GalleryTests(CommunityTestBase):
    def test_legacy_image_still_works(self):
        community = self.make_community('Vieja', image_url='/static/img/comunidad-default.svg')
        self.assertEqual(community.get_image(), '/static/img/comunidad-default.svg')

    def test_single_main_image(self):
        community = self.make_community('G')
        first = CommunityImage.objects.create(community=community, image=image_file('a.jpg'))
        second = CommunityImage.objects.create(community=community, image=image_file('b.jpg'), is_main=True)
        first.refresh_from_db()
        self.assertTrue(second.is_main)
        self.assertFalse(first.is_main)
        self.assertEqual(community.main_image, second)
        self.assertEqual(community.get_image(), second.image.url)

    def test_first_image_becomes_main_and_delete_promotes_next(self):
        community = self.make_community('G')
        first = CommunityImage.objects.create(community=community, image=image_file('a.jpg'))
        second = CommunityImage.objects.create(community=community, image=image_file('b.jpg'), order=1)
        self.assertTrue(first.is_main)
        first.delete()
        second.refresh_from_db()
        self.assertTrue(second.is_main)

    def test_shared_legacy_file_not_deleted(self):
        community = self.make_community('G', image=image_file('legacy.jpg'))
        photo = CommunityImage.objects.create(community=community, image=community.image.name)
        storage, name = community.image.storage, community.image.name
        photo.delete()
        self.assertTrue(storage.exists(name))

    def test_detail_page_shows_gallery(self):
        community = self.make_community('Galeria')
        for i in range(3):
            CommunityImage.objects.create(community=community, image=image_file(f'{i}.jpg'), caption=f'Foto {i}',
                                          order=i)
        response = self.client.get(reverse('communities:detail', args=[community.pk]))
        self.assertContains(response, 'data-gallery-thumb', count=3)
        self.assertContains(response, '3 fotos')


class AdminGalleryTests(CommunityTestBase):
    def test_admin_multi_upload(self):
        admin = User.objects.create_superuser('admin@test.com', 'admin@test.com', 'clave-segura-123')
        self.client.force_login(admin)
        community = self.make_community('Admin')
        url = reverse('admin:communities_community_change', args=[community.pk])
        data = {
            'name': community.name, 'description': 'Desc', 'province': 'Salta', 'location': 'Paraje X',
            'population': 10, 'email': 'c@test.com', 'is_active': 'on',
            'image_url': '', 'new_images': [image_file('1.jpg'), image_file('2.jpg', 'red')],
            'images-TOTAL_FORMS': 0, 'images-INITIAL_FORMS': 0,
            'needs-TOTAL_FORMS': 0, 'needs-INITIAL_FORMS': 0,
        }
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 302, getattr(response, 'context', None)
                         and response.context['adminform'].form.errors)
        self.assertEqual(community.images.count(), 2)
        self.assertEqual(community.images.filter(is_main=True).count(), 1)


class PublicPagesTests(CommunityTestBase):
    def setUp(self):
        self.community = self.make_community('Pública', location='Paraje Y')
        Need.objects.create(community=self.community, title='Agua potable', description='d', category='Agua',
                            target_amount=Decimal('1000'), is_urgent=True)
        Need.objects.create(community=self.community, title='Útiles', description='d', category='Educación',
                            target_amount=Decimal('1000'), status=Need.Status.COMPLETED)

    def test_home_is_public_and_shows_featured(self):
        response = self.client.get(reverse('home'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'La comunidad que más necesita tu ayuda')
        self.assertContains(response, 'Pública')
        self.assertContains(response, 'https://www.instagram.com/semillasdelalgarrobo/')
        self.assertContains(response, 'https://www.facebook.com/asistenciasolidariaelalgarrobo/')
        self.assertContains(response, 'Seguinos en nuestras redes')

    def test_detail_shows_status_labels(self):
        response = self.client.get(reverse('communities:detail', args=[self.community.pk]))
        self.assertContains(response, 'Necesidad urgente')
        self.assertContains(response, 'Necesidad cubierta')
        self.assertContains(response, 'Quiero ayudar')

    def test_list_is_public(self):
        self.assertEqual(self.client.get(reverse('communities:list')).status_code, 200)

    def test_login_keeps_next(self):
        User.objects.create_user('d@test.com', 'd@test.com', 'clave-segura-123')
        response = self.client.post(reverse('accounts:login'), {
            'tab': 'login', 'username': 'd@test.com', 'password': 'clave-segura-123', 'next': '/donar/unica/',
        })
        self.assertRedirects(response, '/donar/unica/', fetch_redirect_response=False)

    def test_login_rejects_external_next(self):
        User.objects.create_user('d@test.com', 'd@test.com', 'clave-segura-123')
        response = self.client.post(reverse('accounts:login'), {
            'tab': 'login', 'username': 'd@test.com', 'password': 'clave-segura-123',
            'next': 'https://malicioso.example/',
        })
        self.assertRedirects(response, reverse('communities:list'), fetch_redirect_response=False)

    def test_fake_donation_api_restricted_to_staff(self):
        user = User.objects.create_user('d@test.com', 'd@test.com', 'clave-segura-123')
        self.client.force_login(user)
        need = self.community.needs.get(title='Agua potable')
        response = self.client.post(reverse('communities:donate', args=[need.pk]), {'amount': '100'})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(need.raised_amount, Decimal('0'))
