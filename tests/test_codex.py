import asyncio
import json
import sys
import pytest
from bioart.codex import CodexClient, CodexError, executable


def test_cli_protocol_and_reconnect(tmp_path, monkeypatch):
    stub=tmp_path/'codex'
    stub.write_text('#!'+sys.executable+'\n'+'''
import sys,json
for line in sys.stdin:
 m=json.loads(line)
 if 'id' not in m: continue
 method=m['method']
 if method=='initialize': result={'userAgent':'fake'}
 elif method=='config/read': result={'config':{'mcp_servers':{'secret-connector':{}}}}
 elif method=='account/read': result={'account':{'type':'chatgpt','planType':'pro'}}
 elif method=='invalid':
  print(json.dumps({'id':m['id'],'error':{'code':-1,'message':'rejected'}}),flush=True);continue
 elif method=='disconnect': sys.exit(0)
 elif method=='slow': continue
 else: result={}
 print(json.dumps({'id':m['id'],'result':result}),flush=True)
''')
    stub.chmod(0o755);monkeypatch.setenv('BIOART_CODEX_BIN',str(stub))
    async def run():
        c=CodexClient()
        try:
            assert (await c.account())['connected']
            assert c.thread_config=={'mcp_servers.secret-connector.enabled':False}
            with pytest.raises(CodexError,match='rejected'): await c.request('invalid',{})
            with pytest.raises(CodexError,match='초과'): await c.request('slow',{},timeout=.02)
            assert not c.pending
            with pytest.raises(CodexError,match='끊어'): await c.request('disconnect',{})
            await c.proc.wait()
            assert (await c.account())['connected']
        finally: await c.close()
    asyncio.run(run())


def test_cli_discovery_with_gui_path(monkeypatch):
    monkeypatch.delenv('BIOART_CODEX_BIN',raising=False)
    monkeypatch.setenv('PATH','/usr/bin:/bin')
    # Desktop launch must not require shell rc files. This environment has ~/.local/bin/codex.
    from pathlib import Path
    if (Path.home()/'.local/bin/codex').is_file(): assert executable().endswith('/codex')
