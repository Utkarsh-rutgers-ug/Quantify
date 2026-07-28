import importlib
import sys
import unittest
from unittest.mock import patch


class StartupRoleTests(unittest.TestCase):
    def test_wsgi_import_exposes_app_without_starting_sampler(self):
        sys.modules.pop("wsgi", None)

        with patch("quote_sampler.start_quote_sampler") as start_sampler:
            wsgi = importlib.import_module("wsgi")

        self.assertTrue(hasattr(wsgi, "app"))
        start_sampler.assert_not_called()

    def test_run_main_starts_sampler_and_flask_dev_server(self):
        import run

        with patch.object(run, "start_quote_sampler") as start_sampler, patch.object(
            run.app, "run"
        ) as flask_run:
            run.main()

        start_sampler.assert_called_once_with(run.app)
        flask_run.assert_called_once_with(debug=True, use_reloader=False, port=5001)

    def test_worker_main_runs_quote_sampler_worker(self):
        import worker

        with patch.object(worker, "run_quote_sampler_worker") as run_worker:
            worker.main()

        run_worker.assert_called_once_with(worker.app)


if __name__ == "__main__":
    unittest.main()
