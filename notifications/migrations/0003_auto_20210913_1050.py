# Generated by Django 3.1.5 on 2021-09-13 10:50

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('notifications', '0002_auto_20210913_1046'),
    ]

    operations = [
        migrations.AlterField(
            model_name='subscription',
            name='service',
            field=models.CharField(choices=[('S', 'Slack'), ('M', 'Mail')], max_length=1),
        ),
    ]
