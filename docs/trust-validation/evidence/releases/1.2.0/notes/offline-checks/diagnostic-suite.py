import json
import sys
import unittest
from pathlib import Path

ROOT = Path('/Users/jeremymcspadden/orca/workspaces/gsd-path/release-gate')
OUT = Path(__file__).parent
sys.path.insert(0, str(ROOT))
suite = unittest.defaultTestLoader.discover(str(ROOT / 'tests'))
module = sys.modules['test_dispatch_driver']
original = module.DispatchDriverTests.round

def observe(self, *args, **kwargs):
    result = original(self, *args, **kwargs)
    if (self._testMethodName == 'test_fix_tasks_resumes_after_only_first_batch_was_written'
            and kwargs.get('wave') == 2):
        (OUT / 'fix-tasks-round-result.json').write_text(
            json.dumps(result, indent=2, default=str) + '\n')
    return result

module.DispatchDriverTests.round = observe
result = unittest.TextTestRunner(verbosity=1).run(suite)
raise SystemExit(not result.wasSuccessful())
