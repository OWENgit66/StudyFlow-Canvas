import json
import socket
from unittest.mock import Mock

import pytest

from evals import resource_classification as evaluation
from app.models.common import ResourceType


def write_gold(tmp_path, rows):
    path=tmp_path/'gold.json'
    path.write_text(json.dumps(rows),encoding='utf-8')
    return path


def test_mapping_calls_production_function_and_does_not_pass_labels(monkeypatch):
    classify=Mock(return_value=ResourceType.tutorial)
    monkeypatch.setattr(evaluation.production,'classify_resource_type',classify)
    result=evaluation.evaluate([{'sample_id':'1','filename':'a.pdf','module_name':'Module',
        'page_title':'Page','link_title':'Link','nearby_text':'Text','item_title':'Item',
        'display_name':'Display','expected_type':'lecture'}])
    classify.assert_called_once_with(filename='a.pdf',module_title='Module',page_title='Page',
        link_text='Link',nearby_text='Text',item_title='Item',display_name='Display')
    assert result['incorrect']==1 and result['results'][0]['v2_1_prediction']=='tutorial'


def test_metrics_cli_failure_details_and_json_report_without_network(tmp_path,monkeypatch,capsys):
    monkeypatch.setattr(socket.socket,'connect',lambda *a: pytest.fail('Eval must stay offline'))
    path=write_gold(tmp_path,[
        {'sample_id':'1','filename':'Lecture.pdf','expected_type':'lecture'},
        {'sample_id':'2','filename':'a.pdf','page_title':'Tutorial','expected_type':'tutorial'},
        {'sample_id':'3','filename':'Schedule.pdf','expected_type':'other'},
        {'sample_id':'4','filename':'Week5.pdf','expected_type':'tutorial'}])
    output=tmp_path/'report.json'
    assert evaluation.main(['--dataset',str(path),'--output',str(output)])==0
    text=capsys.readouterr().out
    assert '75.00%' in text and '[FAIL] 4' in text and 'Predicted: other' in text
    result=json.loads(output.read_text())
    assert (result['total_samples'],result['correct'],result['incorrect'])==(4,3,1)
    assert result['per_type']['tutorial']['accuracy']==0.5
    assert len(result['dataset_sha256'])==len(result['classifier_sha256'])==64


@pytest.mark.parametrize('rows', [[],{},[{}],[{'sample_id':'1','expected_type':'lab'}],
    [{'sample_id':'1','expected_type':'other','filename':123}],
    [{'sample_id':'1','expected_type':'other'}]*2])
def test_invalid_gold_rejected(tmp_path,rows):
    with pytest.raises(ValueError):evaluation.load_gold(write_gold(tmp_path,rows))


def test_empty_metadata_and_absent_class_denominator(tmp_path):
    rows=evaluation.load_gold(write_gold(tmp_path,[{'sample_id':'x','filename':None,'expected_type':'other'}]))
    result=evaluation.evaluate(rows)
    assert result['correct']==1 and result['per_type']['lecture']['accuracy'] is None


def test_cannot_overwrite_gold(tmp_path):
    path=write_gold(tmp_path,[{'sample_id':'x','expected_type':'other'}])
    original=path.read_bytes()
    with pytest.raises(SystemExit):evaluation.main(['--dataset',str(path),'--output',str(path)])
    assert path.read_bytes()==original
