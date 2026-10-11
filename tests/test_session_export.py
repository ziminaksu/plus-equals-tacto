"""Public Entire exports must not contain credentials or hidden benchmark values."""
import json

from tools.export_codex_session import redact


def test_redacts_nested_tool_output_and_keeps_visible_source_metadata():
    examples = ["{'c_best': 12345.678}", '{"c_best": 12345.678}', r'{\"c_best\": 12345.678}',
                {'c_best': 12345.678}]
    result = redact({'source_record': 19, 'tool_output': examples, 'score': 0.46}, [])
    assert '12345.678' not in json.dumps(result)
    assert json.dumps(result).count('[REDACTED_BENCHMARK]') == 4
    assert result['source_record'] == 19 and result['score'] == 0.46


def test_redacts_supported_key_patterns_and_known_provider_secrets():
    keys = [prefix + 'abcdefghijk1234567890abcdefghijk' for prefix in ('sk-proj-', 'hf_', 'AIza', 'AQ.')]
    keys.append('private-azure-value')
    result = redact({'content': keys}, ['private-azure-value'])
    assert result['content'] == ['[REDACTED_CREDENTIAL]'] * len(keys)
