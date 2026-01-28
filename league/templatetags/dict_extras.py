from django import template

register = template.Library()

@register.filter
def get_item(d, k):
    return d.get(k)


@register.filter
def media_src(file_field):
    """Return a safe <img src> for ImageField/FileField.

    Handles cases where the DB might contain an absolute URL (e.g., Cloudinary)
    instead of a local media path.
    """
    if not file_field:
        return ""

    # Some deployments store an absolute URL in the field name.
    name = getattr(file_field, "name", "") or ""
    if isinstance(name, str) and name.startswith(("http://", "https://", "//")):
        return name

    # Otherwise rely on the storage backend.
    try:
        url = file_field.url
    except Exception:
        return ""

    # If url is already absolute, keep it.
    if isinstance(url, str) and url.startswith(("http://", "https://", "//")):
        return url

    return url or ""
