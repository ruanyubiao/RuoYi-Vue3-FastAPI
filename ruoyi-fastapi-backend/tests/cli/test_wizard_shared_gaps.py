"""Coverage boost for cli.wizard shared pieces: base, aggregators, prompts, presenters."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from types import SimpleNamespace

from pytest import MonkeyPatch

BACKEND_DIR = Path(__file__).resolve().parents[2]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def _load(name: str):
    sys.modules.pop(name, None)
    return importlib.import_module(name)


def test_wizard_base_extract_wrappers() -> None:
    base = _load('cli.wizard.base')
    nested = SimpleNamespace(
        payload={'ok': True},
        returncode=3,
        stdout=' out ',
        stderr=' err ',
    )
    assert base.BaseNestedCommandWizardFlow.extract_payload(nested) == {'ok': True}
    assert base.BaseNestedCommandWizardFlow.extract_returncode(nested) == 3
    assert base.BaseNestedCommandWizardFlow.extract_stdout(nested) == 'out'
    assert base.BaseNestedCommandWizardFlow.extract_stderr(nested) == 'err'

    empty = SimpleNamespace()
    assert base.BaseNestedCommandWizardFlow.extract_payload(empty) is None
    assert base.BaseNestedCommandWizardFlow.extract_returncode(empty) == 0
    assert base.BaseNestedCommandWizardFlow.extract_stdout(empty) == ''
    assert base.BaseNestedCommandWizardFlow.extract_stderr(empty) == ''


def test_wizard_aggregators_payload_and_status() -> None:
    aggregators = _load('cli.wizard.aggregators')
    support = aggregators.ProdCheckPayloadSupport()
    assert support.extract_runtime_payload({'runtime': {'cliEnv': 'dev'}}) == {'cliEnv': 'dev'}
    assert support.extract_runtime_payload(None) is None
    assert support.extract_doctor_payload({'ok': True}) == {'ok': True}
    assert support.extract_doctor_payload('x') is None
    assert support.extract_config_payload({'config': {'name': 'app'}}) == {'name': 'app'}
    assert support.extract_config_payload([]) is None

    evaluator = aggregators.ProdCheckStatusEvaluator()
    assert evaluator.is_ok({'ok': True}, {'ok': True}, None) is True
    assert evaluator.is_ok({'ok': True}, {'ok': True}, {'ok': False}) is False
    assert evaluator.is_ok(None, {'ok': True}, None) is False
    assert evaluator.build_message() == '生产巡检完成'

    aggregator = aggregators.ProdCheckAggregator()
    payload = aggregator.build_payload(
        env='prod',
        runtime_payload={'ok': True, 'runtime': {'cliEnv': 'prod'}},
        doctor_payload={'ok': True, 'message': 'fine'},
        config_payload={'ok': True, 'config': {'name': 'n', 'host': 'h', 'port': 1}},
    )
    assert payload['ok'] is True
    assert payload['env'] == 'prod'
    assert payload['runtime']['cliEnv'] == 'prod'
    assert payload['doctor']['ok'] is True
    assert payload['config']['name'] == 'n'


def test_wizard_prompts_retry_and_confirm(monkeypatch: MonkeyPatch) -> None:
    prompts = _load('cli.wizard.prompts')
    service = prompts.WizardPromptService()

    monkeypatch.setattr(
        prompts,
        'ENVIRONMENT_OPTION_SERVICE',
        SimpleNamespace(discover_env_names=lambda: ['dev', 'prod']),
    )
    env_answers = iter(['bad', 'prod'])
    monkeypatch.setattr(prompts.typer, 'prompt', lambda *_a, **_k: next(env_answers))
    echoes: list[str] = []
    monkeypatch.setattr(prompts.typer, 'echo', lambda msg: echoes.append(msg))
    assert service.prompt_env('dev') == 'prod'
    assert echoes

    choice_answers = iter(['nope', 'a'])
    monkeypatch.setattr(prompts.typer, 'prompt', lambda *_a, **_k: next(choice_answers))
    assert service.prompt_choice('pick', ['a', 'b'], 'a') == 'a'

    text_answers = iter(['', '  ', 'value'])
    monkeypatch.setattr(prompts.typer, 'prompt', lambda *_a, **_k: next(text_answers))
    assert service.prompt_required_text('name') == 'value'

    monkeypatch.setattr(prompts.typer, 'prompt', lambda *_a, **_k: ' optional ')
    assert service.prompt_optional_text('note') == 'optional'

    monkeypatch.setattr(prompts.typer, 'confirm', lambda *_a, **_k: True)
    assert service.prompt_confirm('go?') is True


def test_wizard_presenters_build_text() -> None:
    presenters = _load('cli.wizard.presenters')
    support = presenters.ProdCheckRenderingSupport()
    assert 'runtime:' in '\n'.join(support.build_runtime_lines({'cliEnv': 'dev'}))
    assert 'doctor:' in '\n'.join(support.build_doctor_lines({'ok': True, 'message': 'm'}))
    assert 'config:' in '\n'.join(
        support.build_config_lines({'name': 'n', 'host': 'h', 'port': 80, 'dbType': 'pg', 'redisHost': 'r', 'redisPort': 1})
    )

    presenter = presenters.ProdCheckPresenter()
    text = presenter.build_text(
        {
            'ok': True,
            'env': 'prod',
            'message': '生产巡检完成',
            'runtime': {'cliEnv': 'prod', 'configEnv': 'prod', 'envFile': '.env', 'envFileExists': True},
            'doctor': {'ok': True, 'message': 'ok'},
            'config': {'name': 'app', 'host': '127.0.0.1', 'port': 8000, 'dbType': 'mysql', 'redisHost': 'r', 'redisPort': 6379},
        }
    )
    assert 'ok: true' in text
    assert 'runtime:' in text
    assert 'doctor:' in text
    assert 'config:' in text

    sparse = presenter.build_text({'ok': False})
    assert 'ok: false' in sparse
    assert 'runtime:' not in sparse
