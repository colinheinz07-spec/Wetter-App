"""Publish an already committed data update without overwriting concurrent work."""
import subprocess
import time


def push_data(attempts=6, run=subprocess.run, wait=time.sleep):
    if not isinstance(attempts,int) or not 1<=attempts<=8:
        raise ValueError('Invalid publication retry count')
    for attempt in range(attempts):
        fetched=run(['git','fetch','origin','main'],capture_output=True,text=True)
        if fetched.returncode:
            raise RuntimeError('Cannot fetch main before data publication: '+fetched.stderr.strip())
        rebased=run(['git','rebase','FETCH_HEAD'],capture_output=True,text=True)
        if rebased.returncode:
            run(['git','rebase','--abort'],capture_output=True,text=True)
            raise RuntimeError('Concurrent data changes conflict; publication stopped: '+rebased.stderr.strip())
        pushed=run(['git','push','origin','HEAD:refs/heads/main'],capture_output=True,text=True)
        if not pushed.returncode:
            print('Published data commit',flush=True)
            return
        message=(pushed.stdout+'\n'+pushed.stderr).lower()
        race=any(text in message for text in ('fetch first','non-fast-forward','cannot lock ref','failed to update ref'))
        if not race:
            raise RuntimeError('Data push failed: '+pushed.stderr.strip())
        if attempt+1<attempts:
            print(f'Main changed during publication; rebasing before retry {attempt+2}/{attempts}',flush=True)
            wait(min(2**attempt,8))
    raise RuntimeError(f'Main kept changing during {attempts} publication attempts; no history was overwritten')


if __name__=='__main__':
    push_data()
