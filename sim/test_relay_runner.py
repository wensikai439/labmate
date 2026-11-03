import importlib.util,unittest
from pathlib import Path
spec=importlib.util.spec_from_file_location('runner',Path(__file__).resolve().parents[1]/'src/pc-background-launcher/run_cloud.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class Stop:
    value=False
    def exists(self): return self.value
class Tests(unittest.TestCase):
    def test_reconnect(self):
        calls=[];results=iter([2,2,0]);stop=Stop()
        def run():calls.append(1);return next(results)
        self.assertEqual(m.supervise(run,stop,lambda _:None),0);self.assertEqual(len(calls),3)
    def test_stop_waiting(self):
        stop=Stop();calls=[]
        def run():calls.append(1);return 2
        def sleep(_):stop.value=True
        m.supervise(run,stop,sleep);self.assertEqual(len(calls),1)
    def test_board_boot_retry(self):
        stop=Stop();calls=[]
        def run():
            calls.append(1)
            if len(calls)==1:raise SystemExit('Board not ready')
            return 0
        m.supervise(run,stop,lambda _:None);self.assertEqual(len(calls),2)
    def test_stopped(self):
        stop=Stop();stop.value=True
        m.supervise(lambda:self.fail('must not reconnect'),stop)
if __name__ == '__main__':
    unittest.main()
