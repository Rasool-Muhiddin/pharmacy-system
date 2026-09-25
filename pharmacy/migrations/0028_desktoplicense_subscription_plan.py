# Generated manually for the Basic/Gold/Diamond desktop feature packages.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('pharmacy', '0027_rename_pharmacy_ex_pharmac_97cfe0_idx_pharmacy_ex_pharmac_f86b8e_idx_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='desktoplicense',
            name='subscription_plan',
            field=models.CharField(
                choices=[
                    ('basic', 'Basic'),
                    ('gold', 'Gold'),
                    ('diamond', 'Diamond'),
                ],
                default='basic',
                max_length=20,
                verbose_name='باقة النظام',
            ),
        ),
    ]
