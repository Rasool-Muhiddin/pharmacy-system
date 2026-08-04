from django import template
from django.contrib.humanize.templatetags.humanize import intcomma

register = template.Library()


@register.filter
def multiply(value, arg):
    try:
        return int(value) * int(arg)
    except (ValueError, TypeError):
        return 0


@register.filter
def iqd(value):
    if value is None:
        return "-"

    try:
        return f"{intcomma(value)} د.ع"
    except Exception:
        return value