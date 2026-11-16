from django import forms
from django.conf import settings
from django.contrib import admin
from django.core.exceptions import ValidationError
from django.db.models import Max
from django.utils.html import format_html

from .models import Community, CommunityImage, Donation, Need
from .priority import need_score


class MultipleImageInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class MultipleImageField(forms.ImageField):
    """Campo que acepta varias imágenes en un solo envío."""

    def __init__(self, *args, **kwargs):
        kwargs.setdefault('widget', MultipleImageInput(attrs={'accept': 'image/*', 'data-gallery-upload': '1'}))
        kwargs.setdefault('required', False)
        super().__init__(*args, **kwargs)

    def clean(self, data, initial=None):
        if not data:
            return []
        files = data if isinstance(data, (list, tuple)) else [data]
        cleaned = [super(MultipleImageField, self).clean(item, initial) for item in files]
        return [validate_image_size(item) for item in cleaned if item]


def validate_image_size(image):
    limit = settings.COMMUNITY_IMAGE_MAX_MB * 1024 * 1024
    if image and getattr(image, 'size', 0) > limit:
        raise ValidationError(f'Cada imagen debe pesar menos de {settings.COMMUNITY_IMAGE_MAX_MB} MB.')
    return image


class CommunityAdminForm(forms.ModelForm):
    new_images = MultipleImageField(
        label='Agregar fotos a la galería',
        help_text='Podés seleccionar varias fotos a la vez. Se muestran en vista previa antes de guardar. '
                  'La primera foto de una comunidad sin fotos queda como principal.',
    )

    class Meta:
        model = Community
        fields = '__all__'


class CommunityImageInlineForm(forms.ModelForm):
    class Meta:
        model = CommunityImage
        fields = ('image', 'caption', 'order', 'is_main')

    def clean_image(self):
        return validate_image_size(self.cleaned_data.get('image'))


class CommunityImageInline(admin.TabularInline):
    model = CommunityImage
    form = CommunityImageInlineForm
    extra = 0
    fields = ('thumbnail', 'image', 'caption', 'order', 'is_main')
    readonly_fields = ('thumbnail',)
    verbose_name = 'foto'
    verbose_name_plural = 'Galería de fotos (marcá "Eliminar" para quitar una foto, "Principal" para la portada)'

    @admin.display(description='Vista previa')
    def thumbnail(self, obj):
        if not obj.pk or not obj.image:
            return '—'
        return format_html('<img src="{}" alt="" style="height:80px;width:120px;object-fit:cover;border-radius:6px">',
                           obj.image.url)


class NeedInline(admin.TabularInline):
    model = Need
    extra = 0
    fields = ('title', 'category', 'target_amount', 'is_urgent', 'status')


@admin.register(Community)
class CommunityAdmin(admin.ModelAdmin):
    form = CommunityAdminForm
    list_display = ('image_preview', 'name', 'province', 'location', 'population', 'owner', 'is_active',
                    'is_featured', 'photos_count', 'active_needs_count', 'priority_display')
    list_filter = ('province', 'is_active', 'is_featured')
    list_editable = ('is_featured',)
    search_fields = ('name', 'description', 'email', 'location')
    inlines = [CommunityImageInline, NeedInline]
    readonly_fields = ('image_preview',)
    fieldsets = (
        (None, {'fields': ('name', 'description', 'province', 'location', 'population', 'email', 'owner')}),
        ('Visibilidad', {'fields': ('is_active', 'is_featured')}),
        ('Fotos', {'fields': ('image_preview', 'new_images')}),
        ('Imagen anterior (compatibilidad)', {'classes': ('collapse',), 'fields': ('image', 'image_url')}),
    )

    class Media:
        js = ('js/admin_gallery.js',)

    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related('images')

    @admin.display(description='Portada')
    def image_preview(self, obj):
        if not obj.pk:
            return '-'
        return format_html(
            '<img src="{}" alt="" style="height:60px;border-radius:6px;object-fit:cover">',
            obj.get_image(),
        )

    @admin.display(description='Fotos')
    def photos_count(self, obj):
        return len(obj.images.all())

    @admin.display(description='Necesidades activas')
    def active_needs_count(self, obj):
        return obj.active_needs_count

    @admin.display(description='Prioridad')
    def priority_display(self, obj):
        return round(sum(need_score(n) for n in obj.needs.filter(status=Need.Status.ACTIVE)), 1)

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        community = form.instance
        uploads = form.cleaned_data.get('new_images') or []
        if not uploads:
            return
        next_order = (community.images.aggregate(m=Max('order'))['m'] or 0) + 1
        has_main = community.images.filter(is_main=True).exists()
        for index, upload in enumerate(uploads):
            CommunityImage.objects.create(
                community=community,
                image=upload,
                order=next_order + index,
                is_main=not has_main and index == 0,
            )


@admin.register(Need)
class NeedAdmin(admin.ModelAdmin):
    list_display = ('title', 'community', 'category', 'target_amount', 'raised_display', 'is_urgent', 'status',
                    'priority_display')
    list_filter = ('category', 'is_urgent', 'status', 'community__province')
    search_fields = ('title', 'description', 'community__name')
    list_editable = ('status', 'is_urgent')

    @admin.display(description='Recaudado')
    def raised_display(self, obj):
        return f'${obj.raised_amount:,.0f} / ${obj.target_amount:,.0f}'

    @admin.display(description='Prioridad')
    def priority_display(self, obj):
        return need_score(obj)


@admin.register(Donation)
class DonationAdmin(admin.ModelAdmin):
    list_display = ('confirmation_code', 'need', 'donor', 'amount', 'created_at')
    list_filter = ('created_at',)
    search_fields = ('confirmation_code', 'need__title', 'donor__username')
    readonly_fields = ('confirmation_code', 'created_at')
