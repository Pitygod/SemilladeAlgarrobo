import uuid
from decimal import Decimal

from django.conf import settings
from django.db import models
from django.db.models import Sum


class Community(models.Model):
    class Province(models.TextChoices):
        SALTA = 'Salta', 'Salta'
        JUJUY = 'Jujuy', 'Jujuy'
        CHACO = 'Chaco', 'Chaco'
        FORMOSA = 'Formosa', 'Formosa'

    owner = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='community_profile',
        verbose_name='usuario responsable',
        null=True,
        blank=True,
    )
    name = models.CharField('nombre', max_length=200)
    description = models.TextField('descripción')
    province = models.CharField('provincia', max_length=50, choices=Province.choices)
    population = models.PositiveIntegerField('población')
    location = models.CharField(
        'ubicación general', max_length=200, blank=True,
        help_text='Ej: "Paraje El Algarrobo, departamento San Martín". Sin direcciones exactas.',
    )
    email = models.EmailField('email de contacto')
    image = models.ImageField(
        'imagen (anterior)', upload_to='communities/', blank=True, null=True,
        help_text='Campo anterior. Para nuevas fotos usá la galería de abajo.',
    )
    image_url = models.CharField(
        'URL de imagen', max_length=500, blank=True,
        help_text='Opcional. Se usa solo si la comunidad no tiene fotos en la galería.',
    )
    is_featured = models.BooleanField(
        'destacar en el inicio', default=False,
        help_text='Si está marcada, se muestra como comunidad destacada antes que el cálculo automático de prioridad.',
    )
    is_active = models.BooleanField('activa', default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'comunidad'
        verbose_name_plural = 'comunidades'
        ordering = ['name']

    def __str__(self):
        return self.name

    @property
    def gallery(self):
        """Fotos de la galería ordenadas, con la principal primero."""
        images = list(self.images.all())
        images.sort(key=lambda img: (not img.is_main, img.order, img.pk))
        return images

    @property
    def main_image(self):
        gallery = self.gallery
        return gallery[0] if gallery else None

    def get_image(self):
        main = self.main_image
        if main:
            return main.image.url
        if self.image:
            return self.image.url
        if self.image_url:
            return self.image_url
        return '/static/img/comunidad-default.svg'

    @property
    def location_label(self):
        return f'{self.location}, {self.province}' if self.location else self.province

    @property
    def active_needs_count(self):
        return self.needs.filter(status=Need.Status.ACTIVE).count()

    @property
    def urgent_needs_count(self):
        return self.needs.filter(status=Need.Status.ACTIVE, is_urgent=True).count()


class Need(models.Model):
    class Category(models.TextChoices):
        ALIMENTOS = 'Alimentos', 'Alimentos'
        AGUA = 'Agua', 'Agua'
        SALUD = 'Salud', 'Salud'
        ROPA = 'Ropa', 'Ropa'
        EDUCACION = 'Educación', 'Educación'
        VIVIENDA = 'Vivienda', 'Vivienda'
        OTRO = 'Otro', 'Otro'

    class Status(models.TextChoices):
        ACTIVE = 'activa', 'Activa'
        COMPLETED = 'completada', 'Completada'
        CANCELLED = 'cancelada', 'Cancelada'

    community = models.ForeignKey(
        Community,
        on_delete=models.CASCADE,
        related_name='needs',
        verbose_name='comunidad',
    )
    title = models.CharField('título', max_length=200)
    description = models.TextField('descripción')
    category = models.CharField('categoría', max_length=50, choices=Category.choices)
    target_amount = models.DecimalField('monto objetivo', max_digits=12, decimal_places=2)
    is_urgent = models.BooleanField('urgente', default=False)
    status = models.CharField(
        'estado',
        max_length=20,
        choices=Status.choices,
        default=Status.ACTIVE,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'necesidad'
        verbose_name_plural = 'necesidades'
        ordering = ['-is_urgent', '-created_at']

    def __str__(self):
        return self.title

    @property
    def raised_amount(self):
        total = self.donations.aggregate(total=Sum('amount'))['total']
        return total or Decimal('0')

    @property
    def remaining_amount(self):
        return max(self.target_amount - self.raised_amount, Decimal('0'))

    @property
    def progress_percent(self):
        if self.target_amount <= 0:
            return 0
        percent = (self.raised_amount / self.target_amount) * 100
        return min(int(percent), 100)

    @property
    def is_funded(self):
        return self.raised_amount >= self.target_amount

    @property
    def public_status(self):
        """Estado legible para el público: (código de color, texto)."""
        if self.status == self.Status.COMPLETED:
            return 'covered', 'Necesidad cubierta'
        if self.status == self.Status.CANCELLED:
            return 'closed', 'Sin vigencia'
        if self.is_urgent:
            return 'urgent', 'Necesidad urgente'
        return 'active', 'Necesidad activa'


class Donation(models.Model):
    need = models.ForeignKey(
        Need,
        on_delete=models.CASCADE,
        related_name='donations',
        verbose_name='necesidad',
    )
    donor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='donations',
        verbose_name='donante',
    )
    amount = models.DecimalField('monto', max_digits=12, decimal_places=2)
    confirmation_code = models.CharField('código de confirmación', max_length=50, unique=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'donación'
        verbose_name_plural = 'donaciones'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.confirmation_code} - ${self.amount}'

    def save(self, *args, **kwargs):
        if not self.confirmation_code:
            self.confirmation_code = self.generate_code()
        super().save(*args, **kwargs)
        if self.need.is_funded and self.need.status == Need.Status.ACTIVE:
            self.need.status = Need.Status.COMPLETED
            self.need.save(update_fields=['status'])

    @staticmethod
    def generate_code():
        return f'DON-{uuid.uuid4().hex[:12].upper()}'


def community_image_path(instance, filename):
    return f'communities/{instance.community_id or "nueva"}/{filename}'


class CommunityImage(models.Model):
    """Foto de la galería de una comunidad (una comunidad puede tener varias)."""

    community = models.ForeignKey(
        Community, on_delete=models.CASCADE, related_name='images', verbose_name='comunidad',
    )
    image = models.ImageField('imagen', upload_to=community_image_path)
    caption = models.CharField(
        'descripción breve', max_length=200, blank=True,
        help_text='Texto alternativo para accesibilidad y epígrafe de la foto.',
    )
    order = models.PositiveSmallIntegerField('orden', default=0)
    is_main = models.BooleanField('principal', default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'foto de la comunidad'
        verbose_name_plural = 'fotos de la comunidad'
        ordering = ['-is_main', 'order', 'pk']

    def __str__(self):
        return f'Foto {self.pk} de {self.community}'

    @property
    def alt_text(self):
        return self.caption or f'Foto de {self.community.name}'

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        siblings = CommunityImage.objects.filter(community_id=self.community_id).exclude(pk=self.pk)
        if self.is_main:
            # Solo puede haber una foto principal por comunidad.
            siblings.filter(is_main=True).update(is_main=False)
        elif not siblings.filter(is_main=True).exists():
            CommunityImage.objects.filter(pk=self.pk).update(is_main=True)
            self.is_main = True
