#!/usr/bin/env python3
# Part of iKiKu. Licensed under AGPL-3.0.
"""Tell people what changed, in the channel, after a deploy -- and only what a person approved.

    tools/announce.py check                         # the bot can post to the channel? (posts nothing)
    tools/announce.py preview docs/announcements/X.fa.md
    tools/announce.py send docs/announcements/X.fa.md --approved <sha256 printed by preview>

The channel is https://t.me/irikiku. Posting goes through a Telegram bot that is an admin of
the channel; its token lives in ~/.config/ikiku/telegram-bot-token (mode 600) or in
$IKIKU_TELEGRAM_TOKEN, and never in this repository.

WHY `--approved`. An announcement speaks for the cooperative in public, and a post cannot be
taken back from everyone who read it. So `send` refuses unless it is given the checksum of
the exact text somebody approved: `preview` prints it, a person reads the text and says yes,
and the text that is sent is byte for byte that one. Edit a comma and the checksum changes,
and the approval with it.

WHERE IT RUNS. Telegram is filtered in Iran, so this runs from a machine outside Iran,
never from the production host.

The text is Markdown-ish plain text: a first line in **bold** is the headline, and **…** is
bold anywhere. Everything else is sent as written; it is escaped for Telegram's HTML mode.
"""
import argparse
import hashlib
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

CHANNEL = '@irikiku'
TOKEN_FILE = os.path.expanduser('~/.config/ikiku/telegram-bot-token')
LOG_FILE = os.path.expanduser('~/.local/state/ikiku/announcements.log')
LIMIT = 4096          # Telegram's limit for one message, in characters after entity parsing
BOLD = re.compile(r'\*\*(.+?)\*\*')


def token():
    value = os.environ.get('IKIKU_TELEGRAM_TOKEN')
    if not value and os.path.exists(TOKEN_FILE):
        if os.stat(TOKEN_FILE).st_mode & 0o077:
            sys.exit("announce: %s must be readable by you only (chmod 600)" % TOKEN_FILE)
        with open(TOKEN_FILE, encoding='utf-8') as handle:
            value = handle.read().strip()
    if not value:
        sys.exit("announce: no bot token. Make a bot with @BotFather, add it to %s as an admin that "
                 "may post, and put its token in %s (chmod 600)." % (CHANNEL, TOKEN_FILE))
    return value


def api(method, **params):
    url = 'https://api.telegram.org/bot%s/%s' % (token(), method)
    data = urllib.parse.urlencode(params).encode()
    try:
        with urllib.request.urlopen(url, data=data, timeout=30) as response:
            body = json.load(response)
    except urllib.error.HTTPError as error:
        body = json.load(error)
    if not body.get('ok'):
        sys.exit("announce: Telegram said no to %s: %s" % (method, body.get('description')))
    return body['result']


def render(text):
    """Plain text with **bold**, as Telegram HTML."""
    return BOLD.sub(lambda m: '<b>%s</b>' % m.group(1), html.escape(text.strip(), quote=False))


def checksum(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def read(path):
    with open(path, encoding='utf-8') as handle:
        return handle.read()


def preview(path):
    text = read(path)
    visible = BOLD.sub(r'\1', text.strip())
    print(visible)
    print('\n' + '-' * 60)
    print("%d characters of %d; channel %s" % (len(visible), LIMIT, CHANNEL))
    print("approve with:  --approved %s" % checksum(text))
    if len(visible) > LIMIT:
        sys.exit("announce: too long for one message; shorten it")


def send(path, approved, channel):
    text = read(path)
    if checksum(text) != approved:
        sys.exit("announce: this is not the text that was approved (checksum differs). Run preview, "
                 "have it read, and approve the checksum it prints.")
    message = api('sendMessage', chat_id=channel, text=render(text), parse_mode='HTML',
                  disable_web_page_preview='true')
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
    with open(LOG_FILE, 'a', encoding='utf-8') as handle:
        handle.write('%s\t%s\t%s\t%s\n' % (time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), channel,
                                           message['message_id'], os.path.relpath(path)))
    print("sent: https://t.me/%s/%s" % (channel.lstrip('@'), message['message_id']))


def check(channel):
    me = api('getMe')
    chat = api('getChat', chat_id=channel)
    member = api('getChatMember', chat_id=channel, user_id=me['id'])
    can_post = member.get('status') == 'creator' or member.get('can_post_messages')
    print("bot @%s, channel «%s» (%s), status %s, may post: %s"
          % (me['username'], chat.get('title'), channel, member.get('status'), bool(can_post)))
    if not can_post:
        sys.exit("announce: make the bot an admin of %s with the right to post messages" % channel)


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('check', help="can the bot post? (posts nothing)")
    one = sub.add_parser('preview', help="show the text and the checksum to approve")
    one.add_argument('file')
    two = sub.add_parser('send', help="post an approved text")
    two.add_argument('file')
    two.add_argument('--approved', required=True, help="the checksum preview printed, once approved")
    for p in (sub.choices['check'], two):
        p.add_argument('--channel', default=CHANNEL)
    args = parser.parse_args()
    if args.command == 'check':
        check(args.channel)
    elif args.command == 'preview':
        preview(args.file)
    else:
        send(args.file, args.approved, args.channel)


if __name__ == '__main__':
    main()
