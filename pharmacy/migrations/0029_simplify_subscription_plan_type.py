from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('pharmacy', '0028_desktoplicense_subscription_plan'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='subscription',
            name='plan_type',
        ),
    ]