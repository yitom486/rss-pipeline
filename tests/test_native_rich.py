import unittest
from unittest.mock import patch

import requests

from rss_pipeline.clients import native_rich as rich


class Reply:
    status_code = 200

    def __init__(self, body):
        self.body = body

    def json(self):
        return self.body


class NativeRichTests(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.config = patch.multiple(rich.config, TELEGRAM_BOT_TOKEN='test-secret', TELEGRAM_CHAT_ID='123')
        self.config.start()
        self.pace = patch.object(rich, '_pace_draft')
        self.pace.start()
        self.addCleanup(self.config.stop)
        self.addCleanup(self.pace.stop)

    def post(self, url, **kwargs):
        self.calls.append((url.rsplit('/', 1)[1], kwargs['json']))
        if url.endswith('/sendRichMessageDraft'):
            return Reply({'ok': True, 'result': True})
        return Reply({'ok': True, 'result': {'message_id': 77, 'rich_message': {'blocks': [{'type': 'paragraph'}]}}})

    def test_native_only_stream_persists_exact_text(self):
        events = []
        with patch.object(rich.http, 'post', side_effect=self.post):
            result = rich.stream(iter(['Hello ', '**world**']), on_event=events.append)
        self.assertEqual(result, 'Hello **world**')
        self.assertEqual([c[0] for c in self.calls], ['sendRichMessageDraft', 'sendRichMessageDraft', 'sendRichMessage'])
        self.assertEqual(self.calls[-1][1]['rich_message'], {'markdown': result})
        self.assertEqual(self.calls[0][1]['draft_id'], self.calls[1][1]['draft_id'])
        self.assertFalse(self.calls[0][1]['can_stop'])
        self.assertEqual(events[-1]['message_id'], 77)

    def test_api_rejection_does_not_fallback(self):
        with patch.object(rich.http, 'post', return_value=Reply({'ok': False, 'error_code': 400, 'description': 'invalid rich text'})) as post:
            with self.assertRaisesRegex(rich.NativeRichError, 'invalid rich text'):
                rich.stream(['hello'])
        self.assertEqual(post.call_count, 1)

    def test_rate_limit_retries_same_native_method(self):
        replies = [Reply({'ok': False, 'error_code': 429, 'parameters': {'retry_after': 2}}), Reply({'ok': True, 'result': True})]
        with patch.object(rich.http, 'post', side_effect=replies) as post, patch.object(rich.time, 'sleep') as sleep:
            rich.send_draft(1, 'hello')
        self.assertEqual(post.call_count, 2)
        self.assertEqual(post.call_args_list[0].args, post.call_args_list[1].args)
        sleep.assert_called_once_with(2.1)

    def test_timeout_redacts_credentials_and_does_not_duplicate_final(self):
        with patch.object(rich.http, 'post', side_effect=requests.Timeout('https://api.telegram.org/bottest-secret/sendRichMessage')) as post:
            with self.assertRaises(rich.NativeRichError) as err:
                rich.send_message('hello')
        self.assertNotIn('test-secret', str(err.exception))
        self.assertEqual(post.call_count, 1)

    def test_requires_native_final_confirmation(self):
        with patch.object(rich.http, 'post', return_value=Reply({'ok': True, 'result': {'message_id': 77, 'text': 'hello'}})):
            with self.assertRaisesRegex(rich.NativeRichError, 'native rich message'):
                rich.send_message('hello')

    def test_empty_stream_does_not_send_final(self):
        with patch.object(rich.http, 'post', side_effect=self.post):
            with self.assertRaisesRegex(rich.NativeRichError, 'Empty generation'):
                rich.stream([])
        self.assertEqual([c[0] for c in self.calls], ['sendRichMessageDraft'])


if __name__ == '__main__':
    unittest.main()
