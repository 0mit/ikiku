# Part of iKiKu. Licensed under AGPL-3.0.
"""Photos of a person or a café, public only after a person here has looked at them.

Anybody may add a photo of themselves or of their café; nobody sees it but them until a staff
member approves it (operator, 2026-09-18). A photo is a public act -- a face, a storefront --
and بند ۷ puts people's safety before the system's openness, so the look is a person's, and a
rejection says why.

What a photo carries besides the picture is removed on the way in: the file is decoded and
written again as a plain JPEG, so no EXIF survives -- above all no GPS position, which would
turn a portrait taken at home into an address.

The only door out is /ikiku/photo/<id> (ikiku_portal), which serves an approved photo to
anyone and any other only to its owner or to staff.
"""
import base64
import io

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError

MAX_BYTES = 8 * 1024 * 1024      # what a phone camera sends, with room
MAX_SIDE = 1600                  # enough for a card and a page; nothing larger is kept
PER_OWNER = 6                    # waiting and approved together
QUALITY = 85


def clean_image(data):
    """The picture and nothing else: decoded, turned upright, shrunk, written again as JPEG.
    Raises UserError for anything that is not a picture a person would recognise as one."""
    from PIL import Image, ImageOps
    if not data:
        raise UserError("عکسی نرسید.")
    if len(data) > MAX_BYTES:
        raise UserError("عکس بزرگ‌تر از ۸ مگابایت است.")
    try:
        with Image.open(io.BytesIO(data)) as probe:
            probe.verify()
        image = Image.open(io.BytesIO(data))
        image = ImageOps.exif_transpose(image)
        image = image.convert('RGB')
    except UserError:
        raise
    except Exception:
        raise UserError("این فایل عکس نیست یا خراب است.") from None
    image.thumbnail((MAX_SIDE, MAX_SIDE))
    out = io.BytesIO()
    image.save(out, format='JPEG', quality=QUALITY, optimize=True)   # no exif= : none is written
    return base64.b64encode(out.getvalue())


class IkikuPhoto(models.Model):
    _name = 'ikiku.photo'
    _description = "عکس"
    _inherit = ['ikiku.publishable']
    _order = 'state, create_date desc, id desc'

    partner_id = fields.Many2one('res.partner', string="شخص", index=True, ondelete='cascade')
    business_id = fields.Many2one('ikiku.business', string="کسب‌وکار", index=True, ondelete='cascade')
    image = fields.Image("عکس", required=True, max_width=MAX_SIDE, max_height=MAX_SIDE)
    state = fields.Selection([('pending', "در انتظارِ بررسی"), ('approved', "تأییدشده"), ('rejected', "ردشده")],
                             string="وضعیت", default='pending', required=True, index=True)
    is_public = fields.Boolean("عمومی", compute='_compute_is_public', store=True,
                               help="فقط عکسِ تأییدشده عمومی است.")
    reject_reason = fields.Text("دلیلِ رد", help="بدونِ دلیلِ نوشته‌شده هیچ عکسی رد نمی‌شود.")
    reviewed_by = fields.Many2one('res.users', string="بررسی کرد", readonly=True)
    reviewed_on = fields.Datetime("زمانِ بررسی", readonly=True)

    @api.depends('state')
    def _compute_is_public(self):
        for photo in self:
            photo.is_public = photo.state == 'approved'

    @api.constrains('partner_id', 'business_id')
    def _check_one_owner(self):
        for photo in self:
            if bool(photo.partner_id) == bool(photo.business_id):
                raise ValidationError("هر عکس مالِ یک نفر یا یک کسب‌وکار است.")

    @api.model
    def ikiku_add(self, data, partner=None, business=None):
        """A new photo, waiting for a person to look at it. `data` is the uploaded file's bytes."""
        owner = [('partner_id', '=', partner.id)] if partner else [('business_id', '=', business.id)]
        if self.sudo().search_count(owner + [('state', 'in', ('pending', 'approved'))]) >= PER_OWNER:
            raise UserError("بیشتر از %s عکس نمی‌شه گذاشت؛ اول یکی رو بردارید." % PER_OWNER)
        return self.sudo().create({'image': clean_image(data),
                                   'partner_id': partner.id if partner else False,
                                   'business_id': business.id if business else False})

    def _check_staff(self):
        if not (self.env.su or self.env.user.has_group('ikiku_base.group_ikiku_staff')):
            raise UserError("فقط همکارانِ ایکیکو عکس را تأیید یا رد می‌کنند.")

    def action_approve(self):
        self._check_staff()
        self.write({'state': 'approved', 'reject_reason': False, 'reviewed_by': self.env.user.id,
                    'reviewed_on': fields.Datetime.now()})
        return True

    def action_reject(self):
        self._check_staff()
        for photo in self:
            if not (photo.reject_reason or '').strip():
                raise UserError("دلیلِ رد را بنویسید؛ صاحبِ عکس آن را می‌بیند.")
        self.write({'state': 'rejected', 'reviewed_by': self.env.user.id, 'reviewed_on': fields.Datetime.now()})
        return True


class ResPartner(models.Model):
    _inherit = 'res.partner'

    def ikiku_approved_photo_id(self):
        """The id of this person's first approved photo, or False: what another side may show."""
        self.ensure_one()
        photo = self.env['ikiku.photo'].sudo().search([('partner_id', '=', self.id), ('is_public', '=', True)], limit=1)
        return photo.id or False
