from django.core.management.base import BaseCommand

from notifications import utils


class Command(BaseCommand):
    help = 'Test notifications'

    def add_arguments(self, parser):
        parser.add_argument('event_name', type=str, help='Event name')
        parser.add_argument('message', type=str, help='Message')
        parser.add_argument('-s', '--subject', type=str, default=None, help='Subject')
        parser.add_argument('--create-link', action='store_true', help='Create link')

    def handle(self, *args, **options):
        x = utils.notify(
            options['event_name'], options['message'], subject=options['subject'], create_link=options['create_link']
        )
        if not x:
            self.stderr.write('No notifications created... Is the event setup? Are there any subscriptions?')
        else:
            self.stdout.write(f'{x} notifications created')
