# Part of iKiKu. Licensed under AGPL-3.0.
"""Signing in with a proven SIM (operator, 2026-09-16, D-1 B).

The documented hook for another way in is _check_credentials, the same one
auth_passkey uses. The credential carries the login and a single-use token that
ikiku.mobile.challenge issued after the SMS code was proven. It is accepted only
for portal (share) users: an SMS never opens a staff account.
"""
from odoo import models
from odoo.exceptions import AccessDenied


class ResUsers(models.Model):
    _inherit = 'res.users'

    def _check_credentials(self, credential, env):
        if credential.get('type') != 'ikiku_sms':
            return super()._check_credentials(credential, env)
        user = self.env.user
        if not user.share or not self.env['ikiku.mobile.challenge'].sudo()._consume_login_token(
                user, credential.get('token')):
            raise AccessDenied()
        # 'default', not 'skip': a portal user who turned on two-factor sign-in at /my/security
        # is still asked for it after the SMS code.
        return {'uid': user.id, 'auth_method': 'ikiku_sms', 'mfa': 'default'}
