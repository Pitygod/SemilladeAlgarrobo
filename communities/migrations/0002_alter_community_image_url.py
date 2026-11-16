from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('communities', '0001_initial'),
    ]

    operations = [
        migrations.AlterField(
            model_name='community',
            name='image_url',
            field=models.CharField(
                blank=True,
                help_text='Opcional. Si subís una imagen arriba, esa tiene prioridad.',
                max_length=500,
                verbose_name='URL de imagen',
            ),
        ),
    ]
