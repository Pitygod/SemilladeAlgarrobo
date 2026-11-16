from django.db.models.signals import post_delete
from django.dispatch import receiver

from .models import Community, CommunityImage


@receiver(post_delete, sender=CommunityImage)
def delete_image_file(sender, instance, **kwargs):
    """Borra el archivo físico al eliminar una foto, salvo que otro registro lo use.

    Las fotos migradas desde el campo anterior ``Community.image`` comparten el
    mismo archivo, por eso se verifica antes de borrarlo.
    """
    name = instance.image.name if instance.image else ''
    if not name:
        return
    still_used = (CommunityImage.objects.filter(image=name).exists()
                  or Community.objects.filter(image=name).exists())
    if not still_used:
        instance.image.storage.delete(name)

    # Si se borró la principal, otra foto pasa a ser la principal.
    if instance.is_main:
        next_image = CommunityImage.objects.filter(community_id=instance.community_id).order_by('order', 'pk').first()
        if next_image:
            CommunityImage.objects.filter(pk=next_image.pk).update(is_main=True)
