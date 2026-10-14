import io
import json
import pytest
from cloud_budget import claim_run

class Response:
    def __init__(self,body):self.body=body
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def read(self,*args):return self.body.read(*args)

def test_cloud_budget_denies_without_configuration(monkeypatch):
    monkeypatch.delenv('V16_WORKER_URL',raising=False)
    monkeypatch.delenv('V16_REGISTRATION_SECRET',raising=False)
    with pytest.raises(RuntimeError,match='NOT_CONFIGURED'):claim_run()

def test_cloud_budget_true_false(monkeypatch):
    monkeypatch.setenv('V16_WORKER_URL','https://example.workers.dev')
    monkeypatch.setenv('V16_REGISTRATION_SECRET','testsecret')
    for allowed in (True,False):
        def opener(req,timeout):
            assert req.full_url.endswith('/budget/claim')
            assert req.get_header('Authorization')=='Bearer testsecret'
            return Response(io.BytesIO(json.dumps({'allowed':allowed}).encode()))
        assert claim_run(opener)==allowed

def test_cloud_budget_rejects_invalid_response(monkeypatch):
    monkeypatch.setenv('V16_WORKER_URL','https://example.workers.dev')
    monkeypatch.setenv('V16_REGISTRATION_SECRET','testsecret')
    with pytest.raises(RuntimeError,match='INVALID_RESPONSE'):
        claim_run(lambda *a,**kw:Response(io.BytesIO(b'{}')))
