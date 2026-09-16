# Part of iKiKu. Licensed under AGPL-3.0.
from odoo import fields, models


class IkikuDemandCancel(models.TransientModel):
    _name = 'ikiku.demand.cancel'
    _description = "لغوِ نیاز با دلیل"

    demand_id = fields.Many2one('ikiku.demand', string="نیاز", required=True)
    reason = fields.Text("دلیلِ لغو", required=True)

    def action_cancel(self):
        self.ensure_one()
        self.demand_id.ikiku_cancel(self.reason)
        return {'type': 'ir.actions.act_window_close'}
