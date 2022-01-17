from dataclasses import dataclass
from typing import List, Optional
from templated_email import get_templated_mail


class Block:
    def render_slack(self, **_):
        raise NotImplementedError('abstract method')

    def render_mail(self, **_):
        raise NotImplementedError('abstract method')


class Empty(Block):
    def render_slack(self, **_):
        return '', {}

    def render_mail(self, **_):
        return '', {}


class Message(Block, list[Block]):
    """
    list of blocks
    """

    def _render(self, block_met, **kw):
        message = []
        kwargs = {}
        for b in self:
            m, k = getattr(b, block_met)(**kw)
            message.append(m)
            full_merge_dict(kwargs, k)
        return '\n'.join(message), kwargs

    def render_slack(self, **_):
        return self._render('render_slack', **_)

    def render_mail(self, **_):
        return self._render('render_mail', **_)


@dataclass
class Basic(Block):
    """
    simple (plain) text message
    """

    message: str

    def render_slack(self, **_):
        return self.message, {}

    def render_mail(self, from_email=None, **_):
        # persist from_email in options
        options = {}
        if from_email:
            options['from_email'] = from_email
        return self.message, options


@dataclass
class Section(Basic):
    """
    block for "Section" type in slack. For mail, renders like Basic
    """

    def render_slack(self, **_):
        return self.message, {'blocks': [{'type': 'section', 'text': {'type': 'mrkdwn', 'text': f'{self.message}'}}]}


class Context(Block, list[str]):
    """
    block for "Context" type in slack. For mail, renders each element like Basic

    TODO: only supports str elements for now
    """

    @property
    def message(self):
        return '\n'.join(self)

    def render_slack(self, **_):
        return self.message, {
            'blocks': [{"type": "context", "elements": [{"type": "mrkdwn", "text": el} for el in self]}]
        }

    def render_mail(self, **_):
        return self.message, {}


@dataclass
class BasicSubject(Basic):
    subject: str

    def render_slack(self, **_):
        return f'{self.subject}: {self.message}', {}

    def render_mail(self, **_):
        m, o = super().render_mail(**_)
        o['subject'] = self.subject
        return m, o


@dataclass
class TemplatedMail(Basic):
    """
    render basic message for slack but use templated-email for email
    """

    template: str
    context: Optional[dict] = None
    create_link: Optional[bool] = False

    def render_mail(self, **kw):
        _, o = super().render_mail(**kw)
        template_message = get_templated_mail(
            template_name=self.template,
            context=self.context,
            from_email=kw.get('from_email'),
            create_link=self.create_link,
            to=kw.get('recipient_list'),
        )
        o['subject'] = template_message.subject
        for alt in template_message.alternatives:
            if alt[1] == 'text/html':
                o['html_message'] = alt[0]
                break

        return template_message.body, o


@dataclass
class ExtraRecipients(Empty):
    emails: List[str]

    def render_mail(self, **_):
        return self.message, {'recipient_list': self.emails}


def full_merge_dict(d_to, d_src):
    """
    based on https://stackoverflow.com/a/56042166

    * replace basic values
    * concatenate lists
    * update dictionaries
    """
    for key, value in d_to.items():
        if key in d_src:
            value2 = d_src[key]
            if type(value) != type(value2):
                raise ValueError('cannot merge different types', type(value), type(value2))
            if type(value) is dict:
                full_merge_dict(d_to[key], d_src[key])
            elif type(value) in (int, float, str):
                d_to[key] = d_src[key]
            elif type(value) is list:
                d_to[key].extend(d_src[key])
            else:
                raise ValueError('merge strategy unknown', type(value))
    for key, value in d_src.items():
        if key not in d_to:
            d_to[key] = value
