# Generated by Django 3.2 on 2023-10-03 09:36

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('privacy', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='issuecategprypassword',
            name='key',
            field=models.CharField(blank=True, max_length=255, null=True),
        ),
        migrations.AddField(
            model_name='issuecategprypassword',
            name='password_data_encrypt',
            field=models.CharField(blank=True, max_length=255, null=True),
        ),
    ]
