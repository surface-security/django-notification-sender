from django.core.management.base import BaseCommand
from django.core.management import call_command

from notifications import utils, models, blocks
from testapp.models import TEST_EVENT


class Command(BaseCommand):
    help = 'Testapp command to send notifications without any setup'

    def add_arguments(self, parser):
        parser.add_argument('target', type=str, help='Target')
        parser.add_argument('message', type=str, help='Message')
        parser.add_argument('--mail', action='store_true', help='Use mail type instead of slack')
        parser.add_argument('-s', '--subject', type=str, default=None, help='Subject')
        parser.add_argument('--create-link', action='store_true', help='Create link')
        parser.add_argument(
            '--spam',
            type=int,
            help='Create multiple messages but DO NOT SEND IMMEDIATELY: to test rate limit handling in notification_sender',
        )

    def handle(self, *args, **options):
        TEST_EVENT.get_event().subscription_set.update_or_create(
            defaults={
                'target': options['target'],
                'service': models.Subscription.Service.MAIL if options['mail'] else models.Subscription.Service.SLACK,
            },
        )
        nblocks = blocks.Message()
        new_domains = ['www.g1.com']
        new_records = [
            'www.g1.com',
            'www.g1.com',
            'www.g1.com',
            'www.g1.com',
            'www.g1.com',
            'www.g1.com',
            'www.g1.com',
            'www.g1.com',
            'www.g1.com',
            'www.g1.com',
            'www.g1.com',
        ]
        new_nameservers = ['www.g1.com', 'www.g1.com', 'www.g1.com', 'www.g1.com', 'www.g1.com']
        if len(new_domains) > 0:
            nblocks.append(blocks.Section(f"*New Domains on AWS:* {len(new_domains)}"))
            nblocks.append(blocks.Context(['\n'.join([domain for domain in new_domains])]))
        if len(new_records) > 0:
            nblocks.append(blocks.Section(f"*New Records on AWS:* {len(new_records)}"))
            nblocks.append(
                blocks.Context(['\n'.join(['%s IN *%s* %s' % (record, record, record) for record in new_records])])
            )
        if len(new_nameservers) > 0:
            nblocks.append(blocks.Section(f"*New Nameservers on AWS:* {len(new_nameservers)}"))
            nblocks.append(blocks.Context(['\n'.join([nameserver for nameserver in new_nameservers])]))
        if nblocks:
            self.stdout.write(nblocks.render_mail()[0])
            x = utils.notify(e.name, nblocks)
            self.stdout.write(f'{x} notifications created')
            call_command('notification_sender', run_once=True)

        if options['spam']:
            x = 0
            for y in range(options['spam']):
                x += utils.notify(
                    e.name,
                    f"{options['message']} ({y})",
                    subject=options['subject'],
                    create_link=options['create_link'],
                )
        else:
            x = utils.notify(e.name, options['message'], subject=options['subject'], create_link=options['create_link'])
        self.stdout.write(f'{x} notifications created')

        if not options['spam']:
            call_command('notification_sender', run_once=True)
