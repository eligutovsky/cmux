#!/bin/bash
python3 -m pip install -q pyyaml pytest bashlex >/dev/null 2>&1
python3 -m pytest -q -p no:cacheprovider -rf tests/test_nightly_build_runner.py tests/test_nightly_trusted_routing.py tests/test_ci_nightly_off_blacksmith.py tests/test_nightly_step_coverage.py tests/test_nightly_sign_runner.py tests/test_ci_nightly_no_hosted_mac.py tests/test_ci_owned_pool_rescue.py 2>&1 | grep -E 'FAILED|Error|passed' | sed 's/^/XX /' | cut -c1-300
