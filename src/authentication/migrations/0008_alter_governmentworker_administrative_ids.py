# Generated by Django 3.2 on 2023-10-24 17:35

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('authentication', '0007_governmentworker_administrative_ids'),
    ]

    operations = [
        migrations.AlterField(
            model_name='governmentworker',
            name='administrative_ids',
            field=models.JSONField(blank=True, null=True, verbose_name='administrative levels'),
        ),
    ]