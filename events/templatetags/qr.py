import base64
from io import BytesIO
import qrcode
from qrcode.image.svg import SvgPathImage
from django import template

register = template.Library()

@register.filter
def qr_data(value):
    # Four-module quiet zone, lossless vector edges, and no artwork over the code.
    code = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=10, border=4)
    code.add_data(str(value))
    code.make(fit=True)
    image = code.make_image(image_factory=SvgPathImage)
    buffer = BytesIO()
    image.save(buffer)
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/svg+xml;base64,{encoded}"
