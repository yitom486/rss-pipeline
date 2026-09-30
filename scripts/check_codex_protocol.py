"""Validate the adapter's outgoing messages against the installed Codex schema."""
import json
from pathlib import Path
import subprocess
import tempfile

from jsonschema import validate
from rss_pipeline import codex_agent, config
from rss_pipeline.clients.codex import AppServer


class Recorder(AppServer):
    def __init__(self):
        self.calls = []

    def request(self, method, params=None, timeout=45):
        self.calls.append((method, params or {}))
        return {'thread': {'id': 'test'}}


def main():
    with tempfile.TemporaryDirectory(prefix='news-codex-schema-') as folder:
        subprocess.run([config.CODEX_BIN, 'app-server', 'generate-json-schema', '--experimental', '--out', folder],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        recorder = Recorder()
        recorder.create_thread(codex_agent.TOOLS)
        recorder.create_thread(codex_agent.COLLECTOR_TOOLS, ephemeral=True)
        recorder.resume_thread('persisted-thread', model='test-model')
        paths = {'thread/start': 'v2/ThreadStartParams.json', 'thread/resume': 'v2/ThreadResumeParams.json'}
        for method, params in recorder.calls:
            validate(params, json.loads((Path(folder) / paths[method]).read_text()))
        validate({'success': True, 'contentItems': [{'type': 'inputText', 'text': '{}'}]},
                 json.loads((Path(folder) / 'DynamicToolCallResponse.json').read_text()))
        print('Installed Codex protocol validation passed: thread/start, thread/resume, dynamic tool response')


if __name__ == '__main__':
    main()
