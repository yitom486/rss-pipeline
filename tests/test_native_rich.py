import unittest
from unittest.mock import patch

import httpx

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

    def test_structured_markdown_survives_chunk_boundaries_and_final_save(self):
        body = (
            '## 实现比较\n\n| 环节 | 作用 |\n| --- | --- |\n| 校验 | 检查来源 |\n\n'
            '依据[^source1]，计算为 $x^2$。\n\n'
            '<details><summary>展开实现细节</summary>\n\n'
            '**补充说明**\n\n</details>\n\n'
            '[^source1]: [案例](https://example.org/case)'
        )
        # Split inside the HTML opening tag, footnote and formula; all must be
        # preserved in the complete draft and final native request, not escaped.
        chunks = [body[index:index + 7] for index in range(0, len(body), 7)]
        with patch.object(rich.http, 'post', side_effect=self.post):
            result = rich.stream(chunks)
        self.assertEqual(result, body)
        for method, payload in self.calls[-2:]:
            self.assertIn(method, ('sendRichMessageDraft', 'sendRichMessage'))
            self.assertEqual(payload['rich_message'], {'markdown': body})
            self.assertNotIn('parse_mode', payload)

    def test_html_is_native_rich_content_for_draft_and_final(self):
        body = '<h2>背景</h2><details><summary>依据</summary><p>说明</p></details>'
        with patch.object(rich.http, 'post', side_effect=self.post):
            rich.send_draft(5, body, format='html')
            rich.send_message(body, format='html')
        self.assertEqual([method for method, _ in self.calls], ['sendRichMessageDraft', 'sendRichMessage'])
        for _, payload in self.calls:
            self.assertEqual(payload['rich_message'], {'html': body})
            self.assertNotIn('parse_mode', payload)

    def test_rate_limit_retries_same_native_method(self):
        replies = [Reply({'ok': False, 'error_code': 429, 'parameters': {'retry_after': 2}}), Reply({'ok': True, 'result': True})]
        with patch.object(rich.http, 'post', side_effect=replies) as post, patch.object(rich.time, 'sleep') as sleep:
            rich.send_draft(1, 'hello')
        self.assertEqual(post.call_count, 2)
        self.assertEqual(post.call_args_list[0].args, post.call_args_list[1].args)
        sleep.assert_called_once_with(2.1)

    def test_timeout_redacts_credentials_and_does_not_duplicate_final(self):
        with patch.object(rich.http, 'post', side_effect=httpx.ReadTimeout('https://api.telegram.org/bottest-secret/sendRichMessage')) as post:
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
