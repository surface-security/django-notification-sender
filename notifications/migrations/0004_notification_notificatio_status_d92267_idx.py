# Generated by Django 3.2.22 on 2023-10-16 11:11

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('notifications', '0003_auto_20210913_1050'),
    ]

    operations = [
        migrations.AddIndex(
            model_name='notification',
            index=models.Index(fields=['status'], name='notificatio_status_d92267_idx'),
        ),
    ]