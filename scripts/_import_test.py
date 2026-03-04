"""Import test for rcs_orchestration — run with the venv Python."""
import sys, traceback
try:
    from rcs_orchestration.orchestrator import Orchestrator
    orch = Orchestrator(r'config\sample_config.yml', run_id='import-test')
    comps = orch._build_components('full')
    ok = all(c is not None for c in comps)
    print('IMPORT_TEST_OK' if ok else 'IMPORT_TEST_PARTIAL')
    for i, comp in enumerate(comps):
        print(f"  component[{i}]: {type(comp).__name__}")
except Exception as e:
    print('IMPORT_TEST_FAIL')
    traceback.print_exc()
    sys.exit(2)
