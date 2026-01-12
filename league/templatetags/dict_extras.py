from django import template

register = template.Library()

@register.filter
def get_item(d, k):
    return d.get(k)
