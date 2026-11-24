"""Exercise publication races and ensure conflicts never become force pushes."""
import runpy
from pathlib import Path
from types import SimpleNamespace

push=runpy.run_path(str(Path(__file__).with_name('push-data-commit.py')))['push_data']


def fixture(fail=None):
    calls=[]
    waits=[]
    def run(command,**kwargs):
        calls.append(command)
        error=fail(command,len([c for c in calls if c[1]=='push'])) if fail else ''
        return SimpleNamespace(returncode=int(bool(error)),stdout='',stderr=error)
    return run,calls,waits


run,calls,waits=fixture(lambda c,n:'! [rejected] HEAD -> main (fetch first)' if c[1]=='push' and n==1 else '')
push(run=run,wait=waits.append)
assert [c[1] for c in calls]==['fetch','rebase','push','fetch','rebase','push']
assert waits==[1]
assert all('--force' not in a for c in calls for a in c)
assert calls[-1]==['git','push','origin','HEAD:refs/heads/main']

for error in ('remote: permission denied','remote: repository rule violation'):
    run,calls,waits=fixture(lambda c,n:error if c[1]=='push' else '')
    try:push(run=run,wait=waits.append)
    except RuntimeError as e:assert 'Data push failed' in str(e)
    else:raise AssertionError('Retried a non-race publication failure')
    assert len(calls)==3 and waits==[]

run,calls,waits=fixture(lambda c,n:'CONFLICT: generated file changed' if c==['git','rebase','FETCH_HEAD'] else '')
try:push(run=run,wait=waits.append)
except RuntimeError as e:assert 'conflict' in str(e)
else:raise AssertionError('Rebase conflict was ignored')
assert calls[-1]==['git','rebase','--abort'] and not any(c[1]=='push' for c in calls)

run,calls,waits=fixture(lambda c,n:'cannot lock ref refs/heads/main' if c[1]=='push' else '')
try:push(attempts=2,run=run,wait=waits.append)
except RuntimeError as e:assert 'no history was overwritten' in str(e)
else:raise AssertionError('Unbounded or silent publication failure')
assert len(calls)==6 and waits==[1]
print('PASS: concurrent push retries, fresh rebase per attempt, bounded failure, permission rejection and conflict abort')
