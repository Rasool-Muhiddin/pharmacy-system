from django.db import migrations, models


def migrate_legacy_plan_types(apps, schema_editor):
    Subscription = apps.get_model('pharmacy', 'Subscription')
    Subscription.objects.filter(plan_type='free').update(plan_type='trial')
    Subscription.objects.filter(
        plan_type__in=('silver', 'gold', 'enterprise'),
    ).update(plan_type='paid')


class Migration(migrations.Migration):

    dependencies = [
        ('pharmacy', '0028_desktoplicense_subscription_plan'),
    ]

    operations = [
        migrations.RunPython(migrate_legacy_plan_types, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='subscription',
            name='plan_type',
            field=models.CharField(
                choices=[
                    ('trial', '⏳ تجريبي'),
                    ('paid', '✅ حقيقي'),
                ],
                default='trial',
                max_length=20,
                verbose_name='نوع الاشتراك',
            ),
        ),
    ]
