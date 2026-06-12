# Refactor `run_job`
1. Create `_JobRunner` class in `crawler/manager.py`.
2. Move the logic of `run_job` into `_JobRunner`.
3. In `_JobRunner`, create methods:
   - `execute()`: Main loop and try/except.
   - `_initialize()`: Parse configs and prepare DB state.
   - `_process_single_url(queue_item)`: The core logic for one URL.
   - `_handle_internal_links(...)`: Handle the internal links from results.
   - `_handle_external_links(...)`: Handle external links with ThreadPoolExecutor.
   - `_handle_request_error(...)`: Handle exceptions.
4. Replace `run_job` in `CrawlerManager` to just instantiate `_JobRunner` and call `execute()`.
5. Remove all `pylint: disable` related to `run_job`.
